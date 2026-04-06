"""
Full prescreening API walkthrough.

Demonstrates a complete session from demographics through to the final
pipeline result (department routing, severity, and differential diagnoses).

Prerequisites:
    1. Start the API server:  uv run prescreen-server
    2. Run this script:       uv run python examples/api_walkthrough.py

The example walks a 28-year-old male patient with a headache through all
8 prescreening phases using the REST API.
"""

import json
import random
import sys
from pathlib import Path

import httpx
import yaml

BASE_URL = "http://localhost:8080/api/v1"
TIMEOUT = 120.0


# ---------------------------------------------------------------------------
# Helper class
# ---------------------------------------------------------------------------

class PrescreenSession:
    """Thin wrapper around the prescreening REST API."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        user_id: str | None = None,
        session_id: str | None = None,
    ):
        self.client = httpx.Client(base_url=base_url, timeout=TIMEOUT)
        self.user_id = user_id or f"patient-{random.randint(1, 1000):03d}"
        self.session_id = session_id or f"session-{random.randint(1, 1000):03d}"

    # -- lifecycle --

    def create(self) -> dict:
        """POST /sessions — create a new prescreening session."""
        resp = self.client.post(
            "/sessions",
            json={"session_id": self.session_id},
            headers={"X-User-ID": self.user_id},
        )
        resp.raise_for_status()
        return resp.json()

    # -- step interaction --

    def get_step(self) -> dict:
        """GET /sessions/{id}/step — fetch the current step."""
        resp = self.client.get(
            f"/sessions/{self.session_id}/step",
            headers={"X-User-ID": self.user_id},
        )
        resp.raise_for_status()
        return resp.json()

    def submit(self, value) -> dict:
        """POST /sessions/{id}/step — submit an answer and advance."""
        resp = self.client.post(
            f"/sessions/{self.session_id}/step",
            headers={"X-User-ID": self.user_id},
            json={"value": value},
        )
        resp.raise_for_status()
        return resp.json()

    def get_history(self) -> list[dict]:
        """GET /sessions/{id}/history — full Q&A trail."""
        resp = self.client.get(
            f"/sessions/{self.session_id}/history",
            headers={"X-User-ID": self.user_id},
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Payloads for each phase
# ---------------------------------------------------------------------------

DEMOGRAPHICS = {
    "age": 28,
    "gender": "Male",
    "underlying_diseases": [],
    "current_medication": {
        "answer": True,
        "detail": (
            "magnesium 2 เม็ดก่อนนอน, zinc+vit c อย่างละเม็ดก่อนนอน "
            "มีกิน acnotin 6 เม็ดต่อวีค, ยาฆ่าเชื้อสิววันละเม็ด "
            "และยาฆ่าเชื้อราสิววีคละ 3 เม็ด"
        ),
    },
    "drug_food_allergies": {"answer": False, "detail": None},
    "surgical_history": {"answer": False, "detail": None},
    "pregnancy_status": "not_pregnant",
    "total_pregnancies": 0,
    "fetuses_count": 0,
    "gestational_age_week": 0,
    "last_menstrual_period": None,
    "menstrual_duration_days": 0,
    "menstrual_flow": None,
}

ER_CRITICAL = {
    "emer_critical_001": False,
    "emer_critical_002": False,
    "emer_critical_003": False,
    "emer_critical_005": False,
    "emer_critical_006": False,
    "emer_critical_007": False,
    "emer_critical_008": False,
    "emer_critical_009": False,
    "emer_critical_010": False,
    "emer_critical_011": False,
    "emer_critical_012": False,
    "emer_critical_013": False,
    "emer_critical_014": False,
    "emer_critical_015": False,
    "emer_critical_016": False,
    "emer_critical_017": False,
    "emer_critical_018": False,
    "emer_critical_019": False,
}

SYMPTOM_SELECTION = {
    "primary_symptom": "Headache",
    "secondary_symptoms": [],
}

ER_CHECKLIST = {
    "emer_adult_hea001": False,
    "emer_adult_hea002": False,
    "emer_adult_hea003": False,
    "emer_adult_hea004": False,
    "emer_adult_hea005": False,
    "emer_adult_hea006": False,
    "emer_adult_hea007": False,
    "emer_adult_hea008": False,
    "emer_adult_hea009": False,
    "emer_adult_hea010": False,
    "emer_adult_hea011": False,
    "emer_adult_hea012": False,
    "emer_adult_hea013": False,
}

# Phase 4 (OLDCARTS) — sequential questions for "Headache"
# Each entry is the answer to one decision-tree node.
OLDCARTS_ANSWERS = [
    "ราวๆสัปดาห์นึง",           # hea_o_001 — onset: when did the headache start?
    "ไม่เคย",                    # hea_o_002 — ever had this before?
    "ค่อย_ๆ_มีอาการ",           # hea_o_003 — sudden or gradual?
    "ไม่เคย",                    # hea_o_004 — history of falls?
    ["ท้ายทอย"],                 # hea_l_001 — location (occipital)
    "ไม่แน่ใจ ไม่เคยสังเกต",    # hea_d_001 — duration per episode
    "ไม่แน่ใจ น่าจะสองสามที",   # hea_d_002 — episodes per day
    ["แน่นๆ"],                   # hea_c_001 — character (tight/pressure)
    "นอนพัก",                    # hea_a_001 — alleviating factor
    "นั่งทำงานนานๆ",            # hea_a_002 — aggravating factor
    "แล้วแต่วัน ส่วนมากเวลาทำงาน",  # hea_t_001 — timing
    2,                           # hea_s_001 — severity (0-10)
    "ไม่มาก ยกเว้นล้ามากๆจริงๆ",    # hea_s_002 — functional impact
    [],                          # hea_as_001 — associated symptoms
    "ไม่มี",                     # hea_as_002 — anything else?
]

PAST_HISTORY = {
    "height": 177.0,
    "weight": 70.2,
    "other_medical_conditions": {"answer": False, "detail": None},
    "vaccination_status": "complete",
    "vaccination_detail": None,
}

PERSONAL_HISTORY = {
    "occupation": "พนักงานบริษัท/เอกชน/ลูกจ้าง",
    "hometown_province": "กรุงเทพ",
    "smoking_history": {"answer": False, "detail": None},
    "alcohol_history": {
        "answer": True,
        "detail": {
            "drinking_frequency": "นาน ๆ ครั้ง",
            "drinking_years": 5,
        },
    },
}

# Phase 7 (OPD) — sequential questions for "Headache"
OPD_ANSWERS = [
    "ไม่มี",                    # hea_opd_004 — brain surgery history?
    "ไม่มี",                    # hea_opd_005 — chronic conditions?
    ["ใช้สายตา นาน ๆ"],         # hea_opd_006 — related symptoms
    [],                          # hea_opd_007 — other history
]


# ---------------------------------------------------------------------------
# Disease lookup — resolve disease_id to name using v1/const/diseases.yaml
# ---------------------------------------------------------------------------

def load_disease_map() -> dict[str, dict]:
    """Load diseases.yaml and return {disease_id: {name, name_th}} mapping."""
    diseases_path = Path(__file__).resolve().parent.parent / "v1" / "const" / "diseases.yaml"
    if not diseases_path.exists():
        return {}
    with open(diseases_path, encoding="utf-8") as f:
        diseases = yaml.safe_load(f)
    return {
        d["id"]: {"name": d["disease_name"], "name_th": d["name_th"]}
        for d in diseases
    }


# ---------------------------------------------------------------------------
# Pretty-printing helpers
# ---------------------------------------------------------------------------

PHASE_NAMES = {
    0: "Demographics",
    1: "ER Critical Screen",
    2: "Symptom Selection",
    3: "ER Checklist",
    4: "OLDCARTS",
    5: "Past History",
    6: "Personal History",
    7: "OPD",
}


def format_answer(answer) -> str:
    """Format an answer value for display."""
    if isinstance(answer, dict):
        # yes_no_detail shape
        if "answer" in answer and "detail" in answer:
            yn = "Yes" if answer["answer"] else "No"
            if answer.get("detail"):
                # Nested detail_fields (e.g. alcohol_history)
                if isinstance(answer["detail"], dict):
                    parts = [f"{k}: {v}" for k, v in answer["detail"].items()]
                    return f"{yn} ({', '.join(parts)})"
                return f"{yn} — {answer['detail']}"
            return yn
        return json.dumps(answer, ensure_ascii=False)
    if isinstance(answer, list):
        if not answer:
            return "(none)"
        return ", ".join(str(a) for a in answer)
    if isinstance(answer, bool):
        return "Yes" if answer else "No"
    return str(answer)


def print_phase_header(phase: int) -> None:
    name = PHASE_NAMES.get(phase, f"Phase {phase}")
    print(f"\n{'=' * 60}")
    print(f"  Phase {phase}: {name}")
    print(f"{'=' * 60}")


def print_result(result: dict, disease_map: dict[str, dict]) -> None:
    """Pretty-print the pipeline result with resolved IDs."""
    print(f"\n{'#' * 60}")
    print(f"  PIPELINE RESULT")
    print(f"{'#' * 60}")

    # -- Departments --
    print("\n  Departments:")
    for dept in result.get("departments", []):
        print(f"    [{dept['id']}] {dept['name']}")
        print(f"           {dept['name_th']}")

    # -- Severity --
    sev = result.get("severity")
    if sev:
        print(f"\n  Severity:")
        print(f"    [{sev['id']}] {sev['name']}")
        print(f"           {sev['name_th']}")

    # -- Diagnoses --
    diagnoses = result.get("diagnoses", [])
    if diagnoses:
        print(f"\n  Differential Diagnoses ({len(diagnoses)}):")
        for i, dx in enumerate(diagnoses, 1):
            did = dx["disease_id"]
            info = disease_map.get(did)
            if info:
                print(f"    {i}. [{did}] {info['name']} — {info['name_th']}")
            else:
                print(f"    {i}. [{did}]")

    # -- Reason / early termination --
    if result.get("reason"):
        print(f"\n  Reason: {result['reason']}")
    if result.get("terminated_early"):
        print(f"\n  (terminated early)")

    print()


def print_history(history: list[dict]) -> None:
    """Pretty-print the full Q&A history grouped by phase."""
    print(f"\n{'#' * 60}")
    print(f"  SESSION HISTORY  ({len(history)} Q&A pairs)")
    print(f"{'#' * 60}")

    current_phase = None
    for qa in history:
        phase = qa.get("phase")
        source = qa.get("source", "")

        # Group header when phase changes
        if source == "llm_generated" and current_phase != "llm":
            current_phase = "llm"
            print(f"\n  --- LLM Follow-up Questions ---")
        elif phase is not None and phase != current_phase:
            current_phase = phase
            name = PHASE_NAMES.get(phase, f"Phase {phase}")
            print(f"\n  --- Phase {phase}: {name} ---")

        qid = qa.get("qid", "")
        question = qa.get("question", "")
        answer = format_answer(qa.get("answer"))

        if qid:
            print(f"    Q: {question}  [{qid}]")
        else:
            print(f"    Q: {question}")
        print(f"    A: {answer}")


# ---------------------------------------------------------------------------
# Main walkthrough
# ---------------------------------------------------------------------------

def run() -> None:
    disease_map = load_disease_map()
    session = PrescreenSession()
    print(f"Creating session  user={session.user_id}  session={session.session_id}")
    session.create()

    # --- Phase 0: Demographics ---
    step = session.get_step()
    print_phase_header(0)
    session.submit(DEMOGRAPHICS)

    # --- Phase 1: ER Critical Screen ---
    step = session.get_step()
    print_phase_header(1)
    session.submit(ER_CRITICAL)

    # --- Phase 2: Symptom Selection ---
    step = session.get_step()
    print_phase_header(2)
    session.submit(SYMPTOM_SELECTION)

    # --- Phase 3: ER Checklist ---
    step = session.get_step()
    print_phase_header(3)
    session.submit(ER_CHECKLIST)

    # --- Phase 4: OLDCARTS (sequential) ---
    print_phase_header(4)
    for answer in OLDCARTS_ANSWERS:
        step = session.get_step()
        q = step["questions"][0]
        print(f"    Q: {q['question']}  [{q['qid']}]")
        print(f"    A: {format_answer(answer)}")
        session.submit(answer)

    # --- Phase 5: Past History ---
    step = session.get_step()
    print_phase_header(5)
    session.submit(PAST_HISTORY)

    # --- Phase 6: Personal History ---
    step = session.get_step()
    print_phase_header(6)
    session.submit(PERSONAL_HISTORY)

    # --- Phase 7: OPD (sequential) ---
    print_phase_header(7)
    for answer in OPD_ANSWERS:
        step = session.get_step()
        q = step["questions"][0]
        print(f"    Q: {q['question']}  [{q['qid']}]")
        print(f"    A: {format_answer(answer)}")
        session.submit(answer)

    # --- LLM follow-up questions (phase 8) ---
    step = session.get_step()
    if step.get("type") == "llm_questions":
        print(f"\n{'=' * 60}")
        print(f"  Phase 8: LLM Follow-up Questions")
        print(f"{'=' * 60}")
        # In a real integration an LLM would answer these; here we prompt
        # the user interactively. Pass --skip-llm to skip this phase.
        if "--skip-llm" in sys.argv:
            print("    (skipped with --skip-llm)")
        else:
            answers = []
            for q in step["questions"]:
                reply = input(f"    Q: {q}\n    A: ")
                answers.append({"question": q, "answer": reply})
            session.submit(answers)

    # --- Final result ---
    result = session.get_step()
    if result.get("type") == "pipeline_result":
        print_result(result, disease_map)
    else:
        print("\nCurrent step (session may need LLM answers to finish):")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    # --- Full Q&A history ---
    history = result.get("history") or session.get_history()
    print_history(history)


if __name__ == "__main__":
    run()
