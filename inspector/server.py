from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Literal, Optional
import hashlib
import subprocess
import sys
import shlex
import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
import yaml
import traceback
from fastapi.exceptions import RequestValidationError

from .loader import load_rules_local, load_constants_local, find_repo_root
from .graph import build_oldcarts_graph, build_opd_graph, build_combined_graph


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


def create_app() -> FastAPI:
    app = FastAPI(title="Prescreen Rules Inspector")

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

    # Serve static assets
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    # Serve image assets from v1/images
    images_dir = find_repo_root() / "v1" / "images"
    if images_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(images_dir)), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        index_html = static_dir / "index.html"
        if not index_html.exists():
            raise HTTPException(status_code=500, detail="Missing frontend index.html")
        return HTMLResponse(index_html.read_text(encoding="utf-8"))

    @app.get("/api/symptoms")
    def list_symptoms() -> Dict[str, Any]:
        consts = load_constants_local()
        symptoms = [c["name"] for c in consts["nhso_symptoms"]]
        rules = load_rules_local()
        available = sorted(set(rules["oldcarts"].keys()) | set(rules["opd"].keys()))
        # return only those in constants and available in rules
        available = [s for s in symptoms if s in available]
        return {"symptoms": available}

    @app.get("/api/version")
    def version() -> Dict[str, Any]:
        root = find_repo_root()
        paths: List[Path] = []
        for rel in ["v1/rules", "v1/const"]:
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
        cmd = "pytest -q tests/test_const_yaml.py tests/test_oldcarts.py tests/test_opd.py"
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
        

    @app.get("/api/graph/{symptom}")
    def get_graph(symptom: str, mode: str = "combined") -> Dict[str, Any]:
        rules = load_rules_local()
        oldcarts = rules["oldcarts"].get(symptom)
        opd = rules["opd"].get(symptom)
        if oldcarts is None and opd is None:
            raise HTTPException(status_code=404, detail=f"Unknown symptom {symptom}")

        if mode == "oldcarts":
            return build_oldcarts_graph(symptom, oldcarts or [])
        elif mode == "opd":
            return build_opd_graph(symptom, opd or [])
        else:
            return build_combined_graph(symptom, oldcarts or [], opd or [])

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


