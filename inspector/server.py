from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Literal, Optional
import hashlib
import subprocess
import shlex
import logging
import os

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
import yaml
from fastapi.exceptions import RequestValidationError

from .loader import load_rules_local, load_er_rules_local, load_demographic_local, load_constants_local, find_repo_root
from .graph import (
    build_oldcarts_graph,
    build_opd_graph,
    build_combined_graph,
)


# ----------------------------------------------------------------------
# Request models (defined at module scope to avoid annotation resolution issues)
# ----------------------------------------------------------------------
class UpdateQuestionRequest(BaseModel):
    source: Optional[Literal["oldcarts", "opd"]] = None
    symptom: str
    qid: str
    data: Dict[str, Any]

    # Provide a readable json-schema-like sample for debugging
    @staticmethod
    def example() -> Dict[str, Any]:  # pragma: no cover - helper for error messages
        return {"source": "oldcarts", "symptom": "Headache", "qid": "hea_d_001", "data": {"qid": "hea_d_001"}}


class UpdateErQuestionRequest(BaseModel):
    mode: str                              # er_symptom | er_adult | er_pediatric
    symptom: Optional[str] = None          # required for adult/pediatric
    qid: str
    data: Dict[str, Any]


class UpdateDemographicRequest(BaseModel):
    qid: str
    data: Dict[str, Any]


def create_app() -> FastAPI:
    app = FastAPI(title="Prescreen Rules Inspector")

    # ------------------------------------------------------------------
    # CORS — allow the Next.js dev server (port 3000) to reach the API
    # ------------------------------------------------------------------
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Logger setup (propagates to uvicorn/root handlers)
    logger = logging.getLogger("inspector")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        logger.addHandler(handler)
        logger.propagate = True
    level_name = os.environ.get("INSPECTOR_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    # ------------------------------------------------------------------
    # Global exception handlers: log details server-side, return minimal JSON
    # ------------------------------------------------------------------
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover - interactive tool
        logger.exception("Unhandled exception at %s", request.url)
        return JSONResponse(status_code=500, content={
            "ok": False,
            "error": "Internal server error",
        })

    @app.exception_handler(ValidationError)
    async def validation_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:  # pragma: no cover - interactive tool
        try:
            body = (await request.body() if hasattr(request, 'body') else b"").decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        logger.warning("ValidationError at %s errors=%s body=%s", request.url, exc.errors(), body[:1000])
        return JSONResponse(status_code=422, content={
            "ok": False,
            "error": "Invalid request",
            "errors": exc.errors(),
        })

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:  # pragma: no cover - interactive tool
        try:
            body = (await request.body() if hasattr(request, 'body') else b"").decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        logger.warning("RequestValidationError at %s errors=%s body=%s", request.url, exc.errors(), body[:1000])
        return JSONResponse(status_code=422, content={
            "ok": False,
            "error": "Invalid request",
            "errors": exc.errors(),
        })

    # ------------------------------------------------------------------
    # Static file serving
    # ------------------------------------------------------------------
    # Prefer the Next.js static export (frontend/out/) over the legacy
    # monolithic index.html (static/).  Both are kept so the old UI
    # remains available as a fallback.
    static_dir = Path(__file__).parent / "static"
    next_out_dir = Path(__file__).parent / "frontend" / "out"

    # Legacy static assets at /static (brand images, etc.)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Serve image assets from v1/images
    images_dir = find_repo_root() / "v1" / "images"
    if images_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(images_dir)), name="assets")

    # Next.js build artifacts at /_next (JS/CSS chunks)
    next_assets = next_out_dir / "_next"
    if next_assets.exists():
        app.mount("/_next", StaticFiles(directory=str(next_assets)), name="next_assets")

    # Brand images at /brand (Next.js public/brand)
    brand_dir = next_out_dir / "brand"
    if brand_dir.exists():
        app.mount("/brand", StaticFiles(directory=str(brand_dir)), name="brand")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        # Prefer Next.js static export
        next_index = next_out_dir / "index.html"
        if next_index.exists():
            return HTMLResponse(next_index.read_text(encoding="utf-8"))
        # Fall back to legacy monolithic index.html
        legacy_index = static_dir / "index.html"
        if legacy_index.exists():
            return HTMLResponse(legacy_index.read_text(encoding="utf-8"))
        raise HTTPException(status_code=500, detail="Missing frontend index.html")

    @app.get("/api/symptoms")
    def list_symptoms() -> Dict[str, Any]:
        consts = load_constants_local()
        symptoms = [c["name"] for c in consts["nhso_symptoms"]]
        rules = load_rules_local()
        available = sorted(set(rules["oldcarts"].keys()) | set(rules["opd"].keys()))
        # return only those in constants and available in rules
        available = [s for s in symptoms if s in available]
        return {"symptoms": available}

    @app.get("/api/constants")
    def get_constants() -> Dict[str, Any]:
        """Return severity levels and departments for editor dropdowns."""
        consts = load_constants_local()
        return {
            "severity_levels": consts["severity_levels"],
            "departments": consts["departments"],
        }

    @app.get("/api/er_symptoms")
    def list_er_symptoms() -> Dict[str, Any]:
        """Return symptom lists available in ER adult and pediatric checklists."""
        er = load_er_rules_local()
        return {
            "adult": sorted(er["er_adult"].keys()),
            "pediatric": sorted(er["er_pediatric"].keys()),
        }

    @app.get("/api/version")
    def version() -> Dict[str, Any]:
        root = find_repo_root()
        paths: List[Path] = []
        for rel in ["v1/rules", "v1/rules/er", "v1/const"]:
            d = root / rel
            if d.exists():
                paths.extend([p for p in d.glob("*.yaml") if p.is_file()])
        h = hashlib.sha256()
        latest_mtime = 0.0
        for p in sorted(paths):
            st = p.stat()
            latest_mtime = max(latest_mtime, st.st_mtime)
            h.update(str(p).encode("utf-8"))
            h.update(str(st.st_mtime_ns).encode("utf-8"))
            h.update(str(st.st_size).encode("utf-8"))
        return {"version": h.hexdigest(), "mtime": latest_mtime}

    def _run_pytest() -> Dict[str, Any]:
        """Run pytest and return result dict."""
        root = find_repo_root()
        cmd = "pytest -q tests/test_const_yaml.py tests/test_demographic.py tests/test_oldcarts.py tests/test_opd.py tests/test_er.py"
        try:
            proc = subprocess.run(
                shlex.split(cmd),
                cwd=str(root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=180,
                text=True,
            )
        except subprocess.TimeoutExpired as e:  # pragma: no cover - interactive tool
            return {"ok": False, "timeout": True, "stdout": e.stdout or "", "stderr": e.stderr or "", "cmd": cmd}
        ok = proc.returncode == 0
        return {"ok": ok, "stdout": proc.stdout, "stderr": proc.stderr, "cmd": cmd, "returncode": proc.returncode}

    @app.get("/api/validate")
    def validate() -> Dict[str, Any]:
        """Run pytest on YAML-related tests and return output."""
        logger.info("Running pytest validation")
        res = _run_pytest()
        if not res.get("ok"):
            logger.warning("Validation FAILED returncode=%s", res.get("returncode"))
        return res

    class UpdateQuestionRequest(BaseModel):
        source: Optional[Literal["oldcarts", "opd"]] = None
        symptom: str
        qid: str
        data: Dict[str, Any]

        # Provide a readable json-schema-like sample for debugging
        @staticmethod
        def example() -> Dict[str, Any]:  # pragma: no cover - helper for error messages
            return {"source": "oldcarts", "symptom": "Headache", "qid": "hea_d_001", "data": {"qid": "hea_d_001"}}

    @app.post("/api/update_question")
    def update_question(req: UpdateQuestionRequest) -> Dict[str, Any]:
        """Update a single question in the YAML, validate with pytest, and rollback on failure.

        The client should keep the qid unchanged. On success returns ok=True and the new repo version.
        """
        root = find_repo_root()
        logger.info("update_question: source=%s symptom=%s qid=%s", req.source, req.symptom, req.qid)

        def try_update(path: Path) -> Dict[str, Any] | None:
            logger.debug("Trying rules file: %s", path)
            if not path.exists():
                raise HTTPException(status_code=500, detail=f"Missing rules file: {path}")
            original = path.read_text(encoding="utf-8")
            try:
                doc_local = yaml.safe_load(original) or {}
            except Exception as e:  # pragma: no cover
                raise HTTPException(status_code=500, detail=f"Failed to parse YAML: {e}")
            if req.symptom not in doc_local:
                logger.debug("Symptom %s not in %s", req.symptom, path)
                return None
            entries_local = doc_local.get(req.symptom) or []
            idx_local = None
            for i, q in enumerate(entries_local):
                if isinstance(q, dict) and q.get("qid") == req.qid:
                    idx_local = i
                    break
            if idx_local is None:
                logger.debug("QID %s not found under symptom %s in %s", req.qid, req.symptom, path)
                return None

            # Enforce qid unchanged
            if isinstance(req.data, dict) and req.data.get("qid") not in (None, req.qid):
                logger.warning("Attempt to change qid from %s to %s", req.qid, req.data.get("qid"))
                return {"ok": False, "error": "Changing qid is not allowed from the editor.", "field": "qid"}

            if not isinstance(req.data, dict):
                logger.warning("data is not an object: got %s", type(req.data).__name__)
                return {"ok": False, "error": "data must be a JSON object", "received_type": type(req.data).__name__}

            new_q_local = dict(req.data)
            new_q_local["qid"] = req.qid
            entries_local[idx_local] = new_q_local
            doc_local[req.symptom] = entries_local

            # Write tentative update
            path.write_text(yaml.safe_dump(doc_local, allow_unicode=True, sort_keys=False), encoding="utf-8")
            logger.debug("Wrote tentative update to %s (symptom=%s qid=%s)", path, req.symptom, req.qid)

            # Validate
            result_local = _run_pytest()
            if not result_local.get("ok"):
                path.write_text(original, encoding="utf-8")
                result_local["rolled_back"] = True
                logger.warning("Tests failed. Rolled back update in %s for qid=%s", path, req.qid)
                return result_local

            logger.info("Update succeeded in %s for qid=%s", path, req.qid)
            return {"ok": True}

        # Determine which file to update
        candidates: List[tuple[str, Path]] = []
        if req.source in ("oldcarts", None):
            candidates.append(("oldcarts", root / "v1" / "rules" / "oldcarts.yaml"))
        if req.source in ("opd", None):
            candidates.append(("opd", root / "v1" / "rules" / "opd.yaml"))

        last_error: Optional[Dict[str, Any]] = None
        for label, path in candidates:
            res = try_update(path)
            if res is None:
                continue
            if res.get("ok"):
                ver = version()
                return {"ok": True, "version": ver, "message": f"Saved to {label}.yaml and tests passed"}
            last_error = res
            # if tests failed on a candidate that matched, stop and return failure
            return res

        if last_error is not None:
            return last_error
        logger.info("QID not found: symptom=%s qid=%s source=%s", req.symptom, req.qid, req.source)
        raise HTTPException(status_code=404, detail=f"QID '{req.qid}' not found under symptom '{req.symptom}' in selected source")
        

    def _compute_graph(symptom: str, mode: str) -> Dict[str, Any]:
        """Build a Cytoscape graph for OLDCARTS / OPD modes only."""
        rules = load_rules_local()
        consts = load_constants_local()
        oldcarts = rules["oldcarts"].get(symptom)
        opd = rules["opd"].get(symptom)
        if oldcarts is None and opd is None:
            raise HTTPException(status_code=404, detail=f"Unknown symptom {symptom}")

        # Lookup maps so terminate nodes show human-readable names
        dept_map = {d["id"]: d["name"] for d in consts["departments"]}
        sev_map = {s["id"]: s["name"] for s in consts["severity_levels"]}

        if mode == "oldcarts":
            return build_oldcarts_graph(symptom, oldcarts or [], dept_map, sev_map)
        elif mode == "opd":
            return build_opd_graph(symptom, opd or [], dept_map, sev_map)
        else:
            return build_combined_graph(symptom, oldcarts or [], opd or [], dept_map, sev_map)

    # Backward-compatible path form, now capturing slashes too
    @app.get("/api/graph/{symptom:path}")
    def get_graph_path(symptom: str, mode: str = "combined") -> Dict[str, Any]:
        return _compute_graph(symptom, mode)

    # Preferred query form avoids any path encoding issues
    @app.get("/api/graph")
    def get_graph_q(symptom: str = Query(...), mode: str = "combined") -> Dict[str, Any]:
        return _compute_graph(symptom, mode)

    # ------------------------------------------------------------------
    # Demographic API — flat list of field definitions
    # ------------------------------------------------------------------

    @app.get("/api/demographic")
    def get_demographic() -> Dict[str, Any]:
        """Return demographic field definitions with resolved ``from_yaml`` values."""
        items = load_demographic_local()
        return {"items": items}

    @app.post("/api/update_demographic")
    def update_demographic(req: UpdateDemographicRequest) -> Dict[str, Any]:
        """Update a single demographic field in the YAML, validate with pytest, and rollback on failure.

        The flat list in ``demographic.yaml`` is searched by qid.  On success
        returns ``{ok: true, version}``.  QID changes are rejected.
        """
        root = find_repo_root()
        logger.info("update_demographic: qid=%s", req.qid)

        # Enforce qid immutability
        if isinstance(req.data, dict) and req.data.get("qid") not in (None, req.qid):
            logger.warning("Attempt to change demographic qid from %s to %s", req.qid, req.data.get("qid"))
            return {"ok": False, "error": "Changing qid is not allowed from the editor.", "field": "qid"}

        if not isinstance(req.data, dict):
            logger.warning("data is not an object: got %s", type(req.data).__name__)
            return {"ok": False, "error": "data must be a JSON object", "received_type": type(req.data).__name__}

        path = root / "v1" / "rules" / "demographic.yaml"
        if not path.exists():
            raise HTTPException(status_code=500, detail=f"Missing demographic rules file: {path}")

        original = path.read_text(encoding="utf-8")
        try:
            doc = yaml.safe_load(original)
        except Exception as e:  # pragma: no cover
            raise HTTPException(status_code=500, detail=f"Failed to parse YAML: {e}")

        if not isinstance(doc, list):
            raise HTTPException(status_code=500, detail="demographic.yaml must be a list")

        # Find the entry by qid
        idx = None
        for i, item in enumerate(doc):
            if isinstance(item, dict) and item.get("qid") == req.qid:
                idx = i
                break
        if idx is None:
            raise HTTPException(status_code=404, detail=f"QID '{req.qid}' not found in demographic.yaml")

        # Apply update (preserving qid)
        new_item = dict(req.data)
        new_item["qid"] = req.qid
        doc[idx] = new_item

        # Write tentative update
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        logger.debug("Wrote tentative demographic update for qid=%s", req.qid)

        # Validate with pytest
        result = _run_pytest()
        if not result.get("ok"):
            path.write_text(original, encoding="utf-8")
            result["rolled_back"] = True
            logger.warning("Tests failed. Rolled back demographic update for qid=%s", req.qid)
            return result

        logger.info("Demographic update succeeded for qid=%s", req.qid)
        ver = version()
        return {"ok": True, "version": ver, "message": "Saved to demographic.yaml and tests passed"}

    # ------------------------------------------------------------------
    # ER Checklist API — flat table data instead of graph
    # ------------------------------------------------------------------

    @app.get("/api/er_checklist")
    def get_er_checklist(mode: str = Query(...), symptom: str = Query("")) -> Dict[str, Any]:
        """Return a flat list of ER checklist items for the table view.

        Modes:
        - ``er_symptom``:    critical symptom screen (no symptom needed)
        - ``er_adult``:      adult checklist for a specific symptom
        - ``er_pediatric``:  pediatric checklist for a specific symptom

        Each item includes pre-resolved severity/department labels so the
        frontend can display human-readable text without extra lookups.
        """
        er = load_er_rules_local()
        consts = load_constants_local()

        # Build lookup dicts for severity and department labels
        sev_map = {s["id"]: s["name"] for s in consts["severity_levels"]}
        dept_map = {d["id"]: d["name"] for d in consts["departments"]}

        # Default routing for ER: Emergency severity + Emergency Medicine dept
        default_sev_id = "sev003"
        default_sev_label = sev_map.get(default_sev_id, "Emergency")
        default_dept_ids = ["dept002"]
        default_dept_labels = [dept_map.get("dept002", "Emergency Medicine")]

        if mode == "er_symptom":
            # Phase 1: flat list of critical yes/no questions — all route to Emergency
            raw_items = er["er_symptom"]
            items = []
            for q in raw_items:
                items.append({
                    "qid": q["qid"],
                    "text": q["text"],
                    "has_override": False,
                    "severity": default_sev_id,
                    "severity_label": default_sev_label,
                    "department": default_dept_ids,
                    "department_labels": default_dept_labels,
                    "raw": q,
                    "source": "er_symptom",
                })
            return {"items": items, "mode": mode, "symptom": None}

        # Adult / Pediatric checklist modes require a symptom
        if not symptom:
            raise HTTPException(status_code=400, detail=f"symptom is required for {mode} mode")

        if mode == "er_adult":
            checklist = er["er_adult"].get(symptom)
            if checklist is None:
                raise HTTPException(status_code=404, detail=f"Unknown ER adult symptom: {symptom}")
            # Adult uses "min_severity" key for severity overrides
            sev_key = "min_severity"
            source = "er_adult"
        elif mode == "er_pediatric":
            checklist = er["er_pediatric"].get(symptom)
            if checklist is None:
                raise HTTPException(status_code=404, detail=f"Unknown ER pediatric symptom: {symptom}")
            # Pediatric uses "severity" key for severity overrides
            sev_key = "severity"
            source = "er_pediatric"
        else:
            raise HTTPException(status_code=400, detail=f"Unknown ER checklist mode: {mode}")

        items = []
        for q in checklist:
            has_override = sev_key in q or "department" in q

            # Resolve severity: use override if present, else default (Emergency)
            if sev_key in q:
                sev_id = q[sev_key].get("id", default_sev_id)
            else:
                sev_id = default_sev_id
            sev_label = sev_map.get(sev_id, sev_id)

            # Resolve department: use override if present, else default (ER)
            if "department" in q:
                d_ids = [d["id"] for d in q["department"]]
            else:
                d_ids = list(default_dept_ids)
            d_labels = [dept_map.get(did, did) for did in d_ids]

            items.append({
                "qid": q["qid"],
                "text": q["text"],
                "has_override": has_override,
                "severity": sev_id,
                "severity_label": sev_label,
                "department": d_ids,
                "department_labels": d_labels,
                "raw": q,
                "source": source,
            })
        return {"items": items, "mode": mode, "symptom": symptom}

    # ------------------------------------------------------------------
    # ER Question Update — parallel to /api/update_question for OLDCARTS/OPD
    # ------------------------------------------------------------------

    @app.post("/api/update_er_question")
    def update_er_question(req: UpdateErQuestionRequest) -> Dict[str, Any]:
        """Update a single ER question in the YAML, validate with pytest, and rollback on failure.

        Works like /api/update_question but targets the ER YAML files:
        - er_symptom  → v1/rules/er/er_symptom.yaml  (flat list)
        - er_adult    → v1/rules/er/er_adult_checklist.yaml  (symptom-keyed dict)
        - er_pediatric → v1/rules/er/er_pediatric_checklist.yaml  (symptom-keyed dict)
        """
        root = find_repo_root()
        logger.info("update_er_question: mode=%s symptom=%s qid=%s", req.mode, req.symptom, req.qid)

        # Enforce qid immutability
        if isinstance(req.data, dict) and req.data.get("qid") not in (None, req.qid):
            logger.warning("Attempt to change qid from %s to %s", req.qid, req.data.get("qid"))
            return {"ok": False, "error": "Changing qid is not allowed from the editor.", "field": "qid"}

        if not isinstance(req.data, dict):
            logger.warning("data is not an object: got %s", type(req.data).__name__)
            return {"ok": False, "error": "data must be a JSON object", "received_type": type(req.data).__name__}

        # Determine which YAML file and how to locate the question
        er_dir = root / "v1" / "rules" / "er"
        if req.mode == "er_symptom":
            path = er_dir / "er_symptom.yaml"
        elif req.mode == "er_adult":
            if not req.symptom:
                raise HTTPException(status_code=400, detail="symptom is required for er_adult mode")
            path = er_dir / "er_adult_checklist.yaml"
        elif req.mode == "er_pediatric":
            if not req.symptom:
                raise HTTPException(status_code=400, detail="symptom is required for er_pediatric mode")
            path = er_dir / "er_pediatric_checklist.yaml"
        else:
            raise HTTPException(status_code=400, detail=f"Unknown ER mode: {req.mode}")

        if not path.exists():
            raise HTTPException(status_code=500, detail=f"Missing ER rules file: {path}")

        original = path.read_text(encoding="utf-8")
        try:
            doc = yaml.safe_load(original)
        except Exception as e:  # pragma: no cover
            raise HTTPException(status_code=500, detail=f"Failed to parse YAML: {e}")

        # Locate the question list depending on mode
        if req.mode == "er_symptom":
            # er_symptom.yaml is a flat list at the top level
            entries = doc if isinstance(doc, list) else []
        else:
            # Adult/pediatric are symptom-keyed dicts
            if not isinstance(doc, dict) or req.symptom not in doc:
                raise HTTPException(
                    status_code=404,
                    detail=f"Symptom '{req.symptom}' not found in {path.name}",
                )
            entries = doc[req.symptom] or []

        # Find the question by qid
        idx = None
        for i, q in enumerate(entries):
            if isinstance(q, dict) and q.get("qid") == req.qid:
                idx = i
                break
        if idx is None:
            raise HTTPException(
                status_code=404,
                detail=f"QID '{req.qid}' not found in {req.mode}"
                       + (f" under symptom '{req.symptom}'" if req.symptom else ""),
            )

        # Apply the update (preserving qid)
        new_q = dict(req.data)
        new_q["qid"] = req.qid
        entries[idx] = new_q

        # For flat-list mode, write the list directly; for dict mode, update the key
        if req.mode == "er_symptom":
            doc = entries
        else:
            doc[req.symptom] = entries

        # Write tentative update
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        logger.debug("Wrote tentative ER update to %s (mode=%s qid=%s)", path, req.mode, req.qid)

        # Validate with pytest
        result = _run_pytest()
        if not result.get("ok"):
            path.write_text(original, encoding="utf-8")
            result["rolled_back"] = True
            logger.warning("Tests failed. Rolled back ER update in %s for qid=%s", path, req.qid)
            return result

        logger.info("ER update succeeded in %s for qid=%s", path, req.qid)
        ver = version()
        return {"ok": True, "version": ver, "message": f"Saved to {path.name} and tests passed"}

    return app


def cli() -> None:
    import uvicorn
    import webbrowser
    url = "http://localhost:8000"
    try:
        # Open browser shortly after server starts
        webbrowser.open_new_tab(url)
    except Exception:
        pass
    uvicorn.run("inspector.server:app", host="0.0.0.0", port=8000, reload=True)


# ASGI app export
app = create_app()


