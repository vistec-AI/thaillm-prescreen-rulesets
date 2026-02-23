#!/usr/bin/env python3
"""API client integration test for the prescreen server.

Exercises all API endpoints across diverse patient profiles by acting as a
pure HTTP client against the live server (unlike ``simulate_pipeline.py``
which calls the SDK directly with a mocked DB).

Iterates over 62 profile combinations (2 age groups x 2 genders x 16 symptoms,
minus Male + Vaginal Discharge) and runs N random sessions per profile,
generating random valid answers and flagging errors or unexpected responses.

Usage::

    # Install deps (first time only)
    uv pip install httpx rich

    # Quick smoke test (1 symptom, 1 run)
    uv run python scripts/run_client_test.py -s Headache -n 1 -v

    # Full run (all 62 profiles x 3 runs = 186 sessions)
    uv run python scripts/run_client_test.py

    # Verbose debug run
    uv run python scripts/run_client_test.py -s Fever --age-group child -n 1 -vv

    # Reproducible run
    uv run python scripts/run_client_test.py --seed 42
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from rich.console import Console
from rich.table import Table

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 16 NHSO symptoms (must match v1/const/nhso_symptoms.yaml)
ALL_SYMPTOMS = [
    "Headache", "Dizziness", "Pain in Joint", "Muscle Pain",
    "Fever", "Cough", "Sore Throat", "Stomachache",
    "Constipation", "Diarrhea", "Dysuria", "Vaginal Discharge",
    "Skin Rash/Lesion", "Wound", "Eye Disorder", "Ear Disorder",
]

# Valid underlying disease names (must match v1/const/underlying_diseases.yaml)
UNDERLYING_DISEASES = [
    "Hypertension", "Dyslipidemia", "Diabetes Mellitus",
    "Chronic kidney disease", "Chronic liver disease", "Heart disease",
    "Thyroid disease", "Stroke", "Obesity",
    "Chronic Obstructive Pulmonary Disease", "Asthma", "Tuberculosis",
    "HIV/AIDS", "Cancer", "Allergy", "Alzheimer disease",
]

GENDERS = ["Male", "Female"]
AGE_GROUPS = ["child", "adult"]

# Pediatric threshold matches the SDK constant (age < 15)
PEDIATRIC_AGE_THRESHOLD = 15

# Pool of random Thai free-text answers
FREE_TEXT_POOL = [
    "ไม่มี",
    "มีบ้างเล็กน้อย",
    "เป็นมาประมาณ 2-3 วัน",
    "ไม่แน่ใจ",
    "มีอาการเป็นพักๆ",
    "ปวดมาก",
    "เริ่มเป็นเมื่อวาน",
    "เป็นมาประมาณสัปดาห์นึง",
]

# Pool of random LLM answers
LLM_ANSWER_POOL = [
    "ปวดมาก",
    "ปวดปานกลาง",
    "ปวดเล็กน้อย",
    "ไม่มี",
    "มีบ้างเป็นบางครั้ง",
    "ไม่แน่ใจ",
    "เริ่มเป็นเมื่อวาน",
    "เป็นมาประมาณสัปดาห์นึง",
]

# Phase names for display
PHASE_NAMES = {
    0: "Demographics",
    1: "ER Critical Screen",
    2: "Symptom Selection",
    3: "ER Checklist",
    4: "OLDCARTS",
    5: "OPD",
}


# ---------------------------------------------------------------------------
# Profile — describes one patient test case
# ---------------------------------------------------------------------------

@dataclass
class Profile:
    """A patient profile for testing — one specific age group + gender + symptom."""

    age_group: str  # "child" or "adult"
    gender: str     # "Male" or "Female"
    symptom: str    # NHSO symptom name

    @property
    def label(self) -> str:
        return f"{self.age_group.title()} {self.gender} — {self.symptom}"

    def date_of_birth(self, rng: random.Random) -> str:
        """Generate a random DOB matching the age group."""
        if self.age_group == "child":
            # Age 1-14 → born 2012-2025
            year = rng.randint(2012, 2025)
        else:
            # Age 15-80 → born 1946-2011
            year = rng.randint(1946, 2011)
        month = rng.randint(1, 12)
        # Keep day safe for all months
        day = rng.randint(1, 28)
        return f"{year}-{month:02d}-{day:02d}"


# ---------------------------------------------------------------------------
# ProfileGenerator — creates all 62 combinations (or filtered subset)
# ---------------------------------------------------------------------------

class ProfileGenerator:
    """Generate test profiles: 2 age groups x 2 genders x 16 symptoms, minus
    Male + Vaginal Discharge = 62 combinations."""

    def __init__(
        self,
        symptoms: list[str] | None = None,
        age_group: str | None = None,
        gender: str | None = None,
    ):
        self._symptoms = symptoms or ALL_SYMPTOMS
        self._age_group = age_group  # None means both
        self._gender = gender        # None means both

    def generate(self) -> list[Profile]:
        profiles = []
        age_groups = [self._age_group] if self._age_group else AGE_GROUPS
        genders = [self._gender] if self._gender else GENDERS

        for ag in age_groups:
            for g in genders:
                for s in self._symptoms:
                    # Skip impossible combination: Male + Vaginal Discharge
                    if g == "Male" and s == "Vaginal Discharge":
                        continue
                    profiles.append(Profile(age_group=ag, gender=g, symptom=s))
        return profiles


# ---------------------------------------------------------------------------
# APIClient — thin httpx wrapper with X-User-ID header
# ---------------------------------------------------------------------------

class APIClient:
    """Async HTTP client for the prescreen server API."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> APIClient:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def health_check(self) -> bool:
        """Check server health. Returns True if server is reachable."""
        try:
            resp = await self._client.get("/health")  # type: ignore[union-attr]
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def create_session(self, user_id: str, session_id: str) -> dict:
        return await self._post(
            "/api/v1/sessions",
            user_id=user_id,
            json={"session_id": session_id},
        )

    async def get_step(self, user_id: str, session_id: str) -> dict:
        return await self._get(
            f"/api/v1/sessions/{session_id}/step",
            user_id=user_id,
        )

    async def submit_answer(
        self, user_id: str, session_id: str, value: Any, qid: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {"value": value}
        if qid is not None:
            body["qid"] = qid
        return await self._post(
            f"/api/v1/sessions/{session_id}/step",
            user_id=user_id,
            json=body,
        )

    async def submit_llm_answers(
        self, user_id: str, session_id: str, answers: list[dict],
    ) -> dict:
        return await self._post(
            f"/api/v1/sessions/{session_id}/llm-answers",
            user_id=user_id,
            json=answers,
        )

    async def _get(self, path: str, user_id: str) -> dict:
        """GET with X-User-ID header, retry once on timeout."""
        headers = {"X-User-ID": user_id}
        try:
            resp = await self._client.get(path, headers=headers)  # type: ignore[union-attr]
        except httpx.TimeoutException:
            # One retry
            resp = await self._client.get(path, headers=headers)  # type: ignore[union-attr]
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, user_id: str, json: Any) -> dict:
        """POST with X-User-ID header, retry once on timeout."""
        headers = {"X-User-ID": user_id}
        try:
            resp = await self._client.post(path, headers=headers, json=json)  # type: ignore[union-attr]
        except httpx.TimeoutException:
            resp = await self._client.post(path, headers=headers, json=json)  # type: ignore[union-attr]
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# AnswerGenerator — random valid answers per phase/question_type
# ---------------------------------------------------------------------------

class AnswerGenerator:
    """Generate random valid answers for each phase and question type."""

    def __init__(self, rng: random.Random, randomize_er: bool = False):
        self._rng = rng
        self._randomize_er = randomize_er

    def demographics(self, profile: Profile) -> dict[str, Any]:
        """Generate phase 0 demographics answer keyed by field key."""
        dob = profile.date_of_birth(self._rng)

        # Random height/weight within plausible ranges
        if profile.age_group == "child":
            height = self._rng.randint(80, 170)
            weight = self._rng.randint(15, 65)
        else:
            height = self._rng.randint(150, 195)
            weight = self._rng.randint(40, 120)

        # Random 0-3 underlying diseases
        num_diseases = self._rng.randint(0, 3)
        diseases = self._rng.sample(UNDERLYING_DISEASES, num_diseases)

        return {
            "date_of_birth": dob,
            "gender": profile.gender,
            "height": height,
            "weight": weight,
            "underlying_diseases": diseases,
        }

    def er_critical(self, questions: list[dict]) -> dict[str, bool]:
        """Generate phase 1 ER critical answers — all False unless randomize_er."""
        if self._randomize_er:
            return {q["qid"]: self._rng.choice([True, False]) for q in questions}
        return {q["qid"]: False for q in questions}

    def symptom_selection(
        self, profile: Profile, all_symptoms: list[str],
    ) -> dict[str, Any]:
        """Generate phase 2 symptom selection answer."""
        # Pick 0-3 random secondary symptoms (excluding primary and
        # excluding Vaginal Discharge for males)
        available = [
            s for s in all_symptoms
            if s != profile.symptom
            and not (profile.gender == "Male" and s == "Vaginal Discharge")
        ]
        num_secondary = self._rng.randint(0, min(3, len(available)))
        secondary = self._rng.sample(available, num_secondary)

        return {
            "primary_symptom": profile.symptom,
            "secondary_symptoms": secondary,
        }

    def er_checklist(self, questions: list[dict]) -> dict[str, bool]:
        """Generate phase 3 ER checklist answers — all False unless randomize_er."""
        if self._randomize_er:
            return {q["qid"]: self._rng.choice([True, False]) for q in questions}
        return {q["qid"]: False for q in questions}

    def sequential_answer(self, question: dict) -> Any:
        """Generate a random valid answer for a sequential-phase question."""
        qtype = question.get("question_type", "")
        options = question.get("options") or []
        fields = question.get("fields") or []
        constraints = question.get("constraints") or {}

        if qtype == "free_text":
            return self._rng.choice(FREE_TEXT_POOL)

        if qtype == "free_text_with_fields":
            if fields:
                return {f["id"]: self._rng.choice(FREE_TEXT_POOL) for f in fields}
            return self._rng.choice(FREE_TEXT_POOL)

        if qtype == "number_range":
            lo = constraints.get("min", constraints.get("min_value", 0))
            hi = constraints.get("max", constraints.get("max_value", 10))
            if isinstance(lo, float) or isinstance(hi, float):
                return round(self._rng.uniform(lo, hi), 1)
            return self._rng.randint(int(lo), int(hi))

        if qtype in ("single_select", "image_single_select"):
            if options:
                return self._rng.choice(options)["id"]
            return "unknown"

        if qtype in ("multi_select", "image_multi_select"):
            if options:
                k = self._rng.randint(1, len(options))
                chosen = self._rng.sample(options, k)
                return [o["id"] for o in chosen]
            return []

        # Fallback: treat as free text
        return self._rng.choice(FREE_TEXT_POOL)

    def llm_answer(self) -> str:
        """Generate a random LLM answer."""
        return self._rng.choice(LLM_ANSWER_POOL)


# ---------------------------------------------------------------------------
# SessionResult — outcome of one session run
# ---------------------------------------------------------------------------

@dataclass
class SessionResult:
    """Outcome of a single session run."""

    profile: Profile
    run_index: int
    status: str = "pending"          # "success", "failed", "incomplete", "terminated"
    departments: list[str] = field(default_factory=list)
    severity: str | None = None
    reason: str | None = None
    terminated_early: bool = False
    phase_counts: dict[int, int] = field(default_factory=dict)
    error: str | None = None
    steps_taken: int = 0


# ---------------------------------------------------------------------------
# RichPrinter — verbosity-aware console output
# ---------------------------------------------------------------------------

class RichPrinter:
    """Verbosity-aware console output using rich."""

    def __init__(self, verbosity: int = 0):
        self.console = Console()
        self.verbosity = verbosity

    def session_header(
        self, index: int, total: int, profile: Profile, run: int, runs: int,
    ) -> None:
        self.console.print(
            f"\n[bold cyan][{index}/{total}][/] "
            f"{profile.label} (run {run}/{runs})"
        )

    def phase_ok(self, phase: int, detail: str) -> None:
        name = PHASE_NAMES.get(phase, f"Phase {phase}")
        self.console.print(f"  [green]\u2713[/] Phase {phase}: {name} — {detail}")

    def phase_error(self, phase: int, detail: str) -> None:
        name = PHASE_NAMES.get(phase, f"Phase {phase}")
        self.console.print(f"  [red]\u2717[/] Phase {phase}: {name} — {detail}")

    def result_line(self, result: SessionResult) -> None:
        if result.terminated_early:
            status_str = "[yellow]TERMINATED EARLY[/]"
        elif result.status == "success":
            status_str = "[green]OK[/]"
        elif result.status == "failed":
            status_str = f"[red]FAILED[/]: {result.error}"
        else:
            status_str = f"[yellow]{result.status.upper()}[/]"

        dept_str = ", ".join(result.departments) if result.departments else "(none)"
        sev_str = result.severity or "(none)"
        self.console.print(f"  \u2192 Result: {dept_str} ({sev_str}) — {status_str}")

        if result.reason:
            self.console.print(f"    Reason: {result.reason}")

    def question_answer(self, question: dict, answer: Any) -> None:
        """Print a Q&A pair (verbosity >= 1)."""
        if self.verbosity < 1:
            return
        qid = question.get("qid", "?")
        qtext = question.get("question", "?")
        qtype = question.get("question_type", "?")
        self.console.print(f"    [dim]Q:[/] {qtext} ({qid}) [{qtype}]")
        self.console.print(f"    [dim]A:[/] {answer}")

    def bulk_answers(self, questions: list[dict], answer: dict, phase: int) -> None:
        """Print bulk-phase Q&A pairs (verbosity >= 1)."""
        if self.verbosity < 1:
            return
        for q in questions:
            qid = q.get("qid", "?")
            # Phase 0 uses metadata.key; other phases use qid
            if phase == 0:
                key = (q.get("metadata") or {}).get("key", qid)
                ans = answer.get(key, "--")
            else:
                ans = answer.get(qid, "--")
            self.question_answer(q, ans)

    def json_payload(self, label: str, data: Any) -> None:
        """Print full JSON payload (verbosity >= 2)."""
        if self.verbosity < 2:
            return
        formatted = json.dumps(data, ensure_ascii=False, indent=2)
        self.console.print(f"    [dim]{label}:[/]")
        self.console.print(f"    {formatted}")

    def warning(self, msg: str) -> None:
        self.console.print(f"  [yellow]![/] {msg}")

    def error(self, msg: str) -> None:
        self.console.print(f"  [red]ERROR[/] {msg}")


# ---------------------------------------------------------------------------
# SessionRunner — drives one session start-to-finish
# ---------------------------------------------------------------------------

class SessionRunner:
    """Run a single prescreening session through the API."""

    def __init__(
        self,
        client: APIClient,
        answer_gen: AnswerGenerator,
        printer: RichPrinter,
        max_steps: int = 100,
    ):
        self._client = client
        self._answer_gen = answer_gen
        self._printer = printer
        self._max_steps = max_steps

    async def run(self, profile: Profile, run_index: int) -> SessionResult:
        """Execute a full session and return the result."""
        result = SessionResult(profile=profile, run_index=run_index)

        # Unique identifiers for this session
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"
        session_id = f"test_session_{uuid.uuid4().hex[:12]}"

        try:
            # --- Step 1: Create session ---
            await self._client.create_session(user_id, session_id)

            # --- Step 2: Get initial step (phase 0) ---
            step = await self._client.get_step(user_id, session_id)
            self._printer.json_payload("Initial step", step)

            steps = 0
            current_phase: int | None = None

            while steps < self._max_steps:
                step_type = step.get("type")

                if step_type == "questions":
                    phase = step.get("phase", -1)
                    questions = step.get("questions", [])
                    result.phase_counts[phase] = result.phase_counts.get(phase, 0)

                    if phase != current_phase:
                        current_phase = phase

                    answer = self._generate_answer(profile, phase, questions, step)

                    self._printer.json_payload("Answer payload", answer)

                    # Submit the answer
                    step = await self._client.submit_answer(
                        user_id, session_id, value=answer,
                    )
                    self._printer.json_payload("Response", step)

                    steps += 1
                    result.steps_taken = steps
                    result.phase_counts[phase] = result.phase_counts.get(phase, 0) + 1

                    # Log the phase result
                    self._log_phase_step(phase, questions, answer, step)

                elif step_type == "llm_questions":
                    # LLM follow-up questions
                    llm_questions = step.get("questions", [])
                    self._printer.phase_ok(
                        5, f"LLM Questions — {len(llm_questions)} questions"
                    )

                    # Generate and submit LLM answers
                    llm_answers = []
                    for q_text in llm_questions:
                        ans = self._answer_gen.llm_answer()
                        llm_answers.append({"question": q_text, "answer": ans})
                        self._printer.question_answer(
                            {"qid": "llm", "question": q_text, "question_type": "llm"},
                            ans,
                        )

                    self._printer.json_payload("LLM answers payload", llm_answers)

                    step = await self._client.submit_llm_answers(
                        user_id, session_id, llm_answers,
                    )
                    self._printer.json_payload("LLM response", step)
                    steps += 1
                    result.steps_taken = steps

                    # After LLM submission, we should get pipeline_result
                    if step.get("type") == "pipeline_result":
                        self._extract_result(step, result)
                        return result

                elif step_type == "pipeline_result":
                    self._extract_result(step, result)
                    return result

                else:
                    self._printer.warning(f"Unexpected step type: {step_type}")
                    result.status = "incomplete"
                    result.error = f"Unexpected step type: {step_type}"
                    return result

            # Exceeded max steps
            result.status = "incomplete"
            result.error = f"Exceeded {self._max_steps} steps"
            return result

        except httpx.HTTPStatusError as exc:
            result.status = "failed"
            error_body = exc.response.text
            result.error = f"HTTP {exc.response.status_code}: {error_body}"
            self._printer.error(result.error)
            return result

        except httpx.TimeoutException:
            result.status = "failed"
            result.error = "Request timed out (after retry)"
            self._printer.error(result.error)
            return result

        except Exception as exc:
            result.status = "failed"
            result.error = f"{type(exc).__name__}: {exc}"
            self._printer.error(result.error)
            return result

    def _generate_answer(
        self, profile: Profile, phase: int, questions: list[dict], step: dict,
    ) -> Any:
        """Dispatch answer generation by phase."""
        if phase == 0:
            return self._answer_gen.demographics(profile)

        if phase == 1:
            return self._answer_gen.er_critical(questions)

        if phase == 2:
            return self._answer_gen.symptom_selection(profile, ALL_SYMPTOMS)

        if phase == 3:
            return self._answer_gen.er_checklist(questions)

        # Phases 4-5: sequential — one question at a time
        if questions:
            return self._answer_gen.sequential_answer(questions[0])

        return "ไม่มี"

    def _log_phase_step(
        self, phase: int, questions: list[dict], answer: Any, response: dict,
    ) -> None:
        """Log one step's outcome."""
        if phase == 0:
            gender = answer.get("gender", "?")
            dob = answer.get("date_of_birth", "?")
            self._printer.phase_ok(phase, f"{gender}, DOB {dob}")
            self._printer.bulk_answers(questions, answer, phase)

        elif phase == 1:
            positives = [qid for qid, v in answer.items() if v is True]
            if positives:
                self._printer.phase_ok(phase, f"positive: {', '.join(positives)}")
            else:
                self._printer.phase_ok(phase, "all clear")
            self._printer.bulk_answers(questions, answer, phase)

        elif phase == 2:
            primary = answer.get("primary_symptom", "?")
            secondary = answer.get("secondary_symptoms", [])
            sec_str = f" + {', '.join(secondary)}" if secondary else ""
            self._printer.phase_ok(phase, f"{primary}{sec_str}")
            self._printer.bulk_answers(questions, answer, phase)

        elif phase == 3:
            positives = [qid for qid, v in answer.items() if v is True]
            if positives:
                self._printer.phase_ok(phase, f"positive: {', '.join(positives)}")
            else:
                self._printer.phase_ok(phase, "all clear")
            self._printer.bulk_answers(questions, answer, phase)

        else:
            # Sequential phase (4 or 5) — logged per question
            if questions:
                self._printer.question_answer(questions[0], answer)

    def _extract_result(self, step: dict, result: SessionResult) -> None:
        """Extract final pipeline result into SessionResult."""
        result.status = "success"
        result.terminated_early = step.get("terminated_early", False)

        # Departments
        departments = step.get("departments", [])
        result.departments = [
            d.get("name", d.get("id", "?")) for d in departments
        ]

        # Severity
        severity = step.get("severity")
        if severity:
            result.severity = severity.get("id", "?")

        # Reason
        result.reason = step.get("reason")

        if result.terminated_early:
            result.status = "terminated"

        # Log the final result
        dept_str = ", ".join(result.departments) if result.departments else "(none)"
        sev_str = result.severity or "(none)"
        self._printer.phase_ok(
            5, f"Result — dept={dept_str}, severity={sev_str}"
        )

        # In verbose mode, show the full result
        self._printer.json_payload("Pipeline result", step)


# ---------------------------------------------------------------------------
# ResultCollector — aggregates results across all sessions
# ---------------------------------------------------------------------------

class ResultCollector:
    """Collect and aggregate session results for the final summary."""

    def __init__(self) -> None:
        self.results: list[SessionResult] = []

    def add(self, result: SessionResult) -> None:
        self.results.append(result)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status in ("success", "terminated"))

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "failed")

    @property
    def incomplete(self) -> int:
        return sum(1 for r in self.results if r.status == "incomplete")

    @property
    def terminated(self) -> int:
        return sum(1 for r in self.results if r.status == "terminated")

    def print_summary(self, console: Console) -> None:
        """Print a rich summary table of all results."""
        console.print("\n")
        console.rule("[bold]Session Summary")
        console.print()

        # --- Counts ---
        console.print(f"  Total:       {self.total}")
        console.print(f"  [green]Passed:[/]      {self.passed}")
        console.print(f"  [red]Failed:[/]      {self.failed}")
        console.print(f"  [yellow]Incomplete:[/]  {self.incomplete}")
        console.print(f"  [yellow]Terminated:[/]  {self.terminated}")
        console.print()

        # --- Per-profile table ---
        table = Table(title="Results by Profile", show_lines=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Profile", min_width=30)
        table.add_column("Run", width=4)
        table.add_column("Status", width=12)
        table.add_column("Steps", width=6)
        table.add_column("Departments", min_width=20)
        table.add_column("Severity", width=10)

        for i, r in enumerate(self.results, 1):
            status_str = {
                "success": "[green]OK[/]",
                "terminated": "[yellow]TERM[/]",
                "failed": "[red]FAIL[/]",
                "incomplete": "[yellow]INC[/]",
            }.get(r.status, r.status)

            dept_str = ", ".join(r.departments) if r.departments else "-"
            sev_str = r.severity or "-"

            table.add_row(
                str(i),
                r.profile.label,
                str(r.run_index),
                status_str,
                str(r.steps_taken),
                dept_str,
                sev_str,
            )

        console.print(table)

        # --- Failed details ---
        failed = [r for r in self.results if r.status == "failed"]
        if failed:
            console.print()
            console.rule("[red]Failed Sessions")
            for r in failed:
                console.print(
                    f"  {r.profile.label} (run {r.run_index}): {r.error}"
                )

        console.print()


# ---------------------------------------------------------------------------
# CLI + async main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="API client integration test for the prescreen server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8080",
        help="Server base URL (default: http://localhost:8080)",
    )
    parser.add_argument(
        "-n", "--runs",
        type=int, default=3,
        help="Number of random runs per profile (default: 3)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="count", default=0,
        help="Increase verbosity (-v for Q&A pairs, -vv for full JSON)",
    )
    parser.add_argument(
        "--seed",
        type=int, default=None,
        help="RNG seed for reproducibility (default: current timestamp)",
    )
    parser.add_argument(
        "-s", "--symptom",
        type=str, default=None,
        help="Filter symptoms (comma-separated, e.g. 'Headache,Fever')",
    )
    parser.add_argument(
        "--age-group",
        choices=["child", "adult"],
        default=None,
        help="Filter by age group (default: both)",
    )
    parser.add_argument(
        "--gender",
        choices=["Male", "Female"],
        default=None,
        help="Filter by gender (default: both)",
    )
    parser.add_argument(
        "--randomize-er",
        action="store_true",
        help="Randomize ER answers (may cause early terminations)",
    )
    parser.add_argument(
        "--max-steps",
        type=int, default=100,
        help="Safety limit: max steps per session (default: 100)",
    )
    parser.add_argument(
        "--timeout",
        type=float, default=30.0,
        help="HTTP request timeout in seconds (default: 30)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    console = Console()

    # --- Seed ---
    seed = args.seed if args.seed is not None else int(time.time())
    rng = random.Random(seed)
    console.print(f"[dim]RNG seed: {seed}[/]")

    # --- Parse symptom filter ---
    symptoms: list[str] | None = None
    if args.symptom:
        symptoms = [s.strip() for s in args.symptom.split(",")]
        # Validate symptom names
        for s in symptoms:
            if s not in ALL_SYMPTOMS:
                console.print(f"[red]Unknown symptom:[/] '{s}'")
                console.print(f"Available: {', '.join(ALL_SYMPTOMS)}")
                sys.exit(1)

    # --- Generate profiles ---
    gen = ProfileGenerator(
        symptoms=symptoms,
        age_group=args.age_group,
        gender=args.gender,
    )
    profiles = gen.generate()

    if not profiles:
        console.print("[red]No profiles match the given filters.[/]")
        sys.exit(1)

    total_sessions = len(profiles) * args.runs
    console.print(
        f"[bold]Running {total_sessions} sessions "
        f"({len(profiles)} profiles x {args.runs} runs)[/]"
    )

    # --- Health check ---
    printer = RichPrinter(verbosity=args.verbose)
    collector = ResultCollector()

    async with APIClient(args.base_url, timeout=args.timeout) as client:
        healthy = await client.health_check()
        if not healthy:
            console.print(
                f"[red]Server at {args.base_url} is not reachable. "
                f"Is the server running?[/]"
            )
            sys.exit(1)
        console.print(f"[green]Server health check passed[/] ({args.base_url})")

        # --- Run sessions ---
        answer_gen = AnswerGenerator(rng, randomize_er=args.randomize_er)
        runner = SessionRunner(
            client, answer_gen, printer, max_steps=args.max_steps,
        )

        session_num = 0
        for profile in profiles:
            for run_idx in range(1, args.runs + 1):
                session_num += 1
                printer.session_header(
                    session_num, total_sessions, profile, run_idx, args.runs,
                )

                result = await runner.run(profile, run_idx)
                printer.result_line(result)
                collector.add(result)

    # --- Summary ---
    collector.print_summary(console)

    # Exit code: 1 if any failures
    if collector.failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
