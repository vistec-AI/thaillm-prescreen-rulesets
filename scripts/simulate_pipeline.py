#!/usr/bin/env python3
"""Simulate the PrescreenPipeline end-to-end with mocked DB and LLM.

Drives through all 8 rule-based phases (demographics, ER critical, symptom
selection, ER checklist, OLDCARTS, past history, personal history, OPD), then
the LLM questioning and prediction stages, printing rich audit logs of every
question asked, the mock answer chosen, and available choices.

By default answers are **randomised** (``--random``, on by default) so each
run explores a different path through the rule graph.  Use ``--no-random``
for the original deterministic behaviour.

Note: the rule-based decision trees usually terminate early (well before
phase 7), so a plain run rarely reaches the LLM/prediction stages.  Pass
``--disable-early-termination`` to force the engine through all 8 phases —
this is required to exercise prediction and the disease-driven custom
termination reason.

Usage::

    # Default run (random symptom + random answers)
    python scripts/simulate_pipeline.py

    # Deterministic run (Headache, fixed answers)
    python scripts/simulate_pipeline.py --no-random

    # Choose a specific symptom with random answers
    python scripts/simulate_pipeline.py -s Fever

    # Run all 8 phases through to prediction (no early exit)
    python scripts/simulate_pipeline.py --no-random --disable-early-termination

    # List available symptoms
    python scripts/simulate_pipeline.py --list-symptoms

    # Verbose mode (include schemas in output)
    python scripts/simulate_pipeline.py -v
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so we can import both the SDK and
# test mock infrastructure.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT / "tests"))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from test_engine import MockRepository, MockSessionRow  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402

from prescreen_rulesets.constants import AUTO_EVAL_TYPES  # noqa: E402
from prescreen_rulesets.engine import PrescreenEngine  # noqa: E402
from prescreen_rulesets.evaluator import ConditionalEvaluator  # noqa: E402
from prescreen_rulesets.interfaces import PredictionModule, QuestionGenerator  # noqa: E402
from prescreen_rulesets.models.action import GotoAction, TerminateAction  # noqa: E402
from prescreen_rulesets.models.pipeline import (  # noqa: E402
    DiagnosisResult,
    GeneratedQuestions,
    LLMAnswer,
    LLMQuestionsStep,
    PipelineResult,
    PredictionResult,
    QAPair,
)
from prescreen_rulesets.models.session import QuestionsStep, TerminationStep  # noqa: E402
from prescreen_rulesets.pipeline import PrescreenPipeline  # noqa: E402
from prescreen_rulesets.ruleset import RulesetStore  # noqa: E402

# ---------------------------------------------------------------------------
# Constants for the simulation
# ---------------------------------------------------------------------------

USER_ID = "sim_user"
SESSION_ID = "sim_session"
_DEFAULT_SYMPTOM = "Headache"

# Phase 0: Hardcoded demographics — an adult male so we use the adult ER
# checklist in phase 3 and avoid pediatric branching.
#
# The demographic schema (v1/rules/demographic.yaml) requires `age`, `gender`,
# `underlying_diseases`, and the three `yes_no_detail` history fields.  A
# `yes_no_detail` value is an object: {"answer": bool[, "detail": {...}]}.
# Female additionally requires the pregnancy block (see the pool below).
MOCK_DEMOGRAPHICS = {
    "age": 31,
    "gender": "Male",
    "underlying_diseases": [],
    "current_medication": {"answer": False},
    "drug_food_allergies": {"answer": False},
    "surgical_history": {"answer": False},
}

# Pool of random demographics for --random mode.
# All entries are adults to avoid pediatric branching edge cases.  Female
# entries carry the not_pregnant block (last_menstrual_period,
# menstrual_duration_days, menstrual_flow) — the schema makes those required
# once pregnancy_status is "not_pregnant".
_RANDOM_DEMOGRAPHICS_POOL = [
    {
        "age": 31, "gender": "Male", "underlying_diseases": [],
        "current_medication": {"answer": False},
        "drug_food_allergies": {"answer": False},
        "surgical_history": {"answer": False},
    },
    {
        "age": 38, "gender": "Female", "underlying_diseases": [],
        "current_medication": {"answer": False},
        "drug_food_allergies": {"answer": False},
        "surgical_history": {"answer": False},
        "pregnancy_status": "not_pregnant",
        "last_menstrual_period": "2026-04-20",
        "menstrual_duration_days": 5, "menstrual_flow": "same",
    },
    {
        "age": 25, "gender": "Male", "underlying_diseases": [],
        "current_medication": {"answer": False},
        "drug_food_allergies": {"answer": False},
        "surgical_history": {"answer": False},
    },
    {
        "age": 50, "gender": "Female", "underlying_diseases": [],
        "current_medication": {"answer": False},
        "drug_food_allergies": {"answer": False},
        "surgical_history": {"answer": False},
        "pregnancy_status": "not_pregnant",
        "last_menstrual_period": "2026-04-15",
        "menstrual_duration_days": 4, "menstrual_flow": "less",
    },
    {
        "age": 36, "gender": "Male", "underlying_diseases": [],
        "current_medication": {"answer": False},
        "drug_food_allergies": {"answer": False},
        "surgical_history": {"answer": False},
    },
]

# Pool of free-text answers for --random mode.
_RANDOM_FREE_TEXT_POOL = [
    "ไม่มี",
    "มีบ้างเล็กน้อย",
    "เป็นมาประมาณ 2-3 วัน",
    "ไม่แน่ใจ",
    "มีอาการเป็นพักๆ",
]

# LLM follow-up questions the mock generator will return.
MOCK_LLM_QUESTIONS = [
    "อาการปวดรุนแรงแค่ไหน?",
    "มีอาการคลื่นไส้ร่วมด้วยไหม?",
]

# Pre-canned answers for the mock LLM questions.
MOCK_LLM_ANSWERS = [
    "ปวดปานกลาง",
    "ไม่มี",
]

# Pool for random LLM answers when --random is active.
_RANDOM_LLM_ANSWER_POOL = [
    "ปวดมาก",
    "ปวดปานกลาง",
    "ปวดเล็กน้อย",
    "ไม่มี",
    "มีบ้างเป็นบางครั้ง",
    "ไม่แน่ใจ",
    "เริ่มเป็นเมื่อวาน",
    "เป็นมาประมาณสัปดาห์นึง",
]


# ---------------------------------------------------------------------------
# Mock LLM components
# ---------------------------------------------------------------------------


class SimQuestionGenerator(QuestionGenerator):
    """Returns a fixed set of Thai follow-up questions."""

    async def generate(self, qa_pairs: list[QAPair]) -> GeneratedQuestions:
        return GeneratedQuestions(questions=MOCK_LLM_QUESTIONS)


class SimPredictionModule(PredictionModule):
    """Returns two mock diagnoses (ranked most-likely first).

    ``DiagnosisResult`` carries only ``disease_id`` — no confidence score is
    exposed, by design, to avoid clinical misinterpretation.

    ``d437`` (Upper respiratory tract infections) is telemedicine-eligible per
    v1/const/disease_reasons.yaml, so it exercises the disease-driven custom
    termination reason: the pipeline should surface the telemedicine note in
    ``PipelineResult.reason``.  ``d001`` is *not* configured — keeping it first
    verifies the "any match wins" scan skips it and still finds ``d437``.
    """

    async def predict(self, qa_pairs: list[QAPair]) -> PredictionResult:
        return PredictionResult(
            diagnoses=[
                DiagnosisResult(disease_id="d001"),
                DiagnosisResult(disease_id="d437"),
            ],
            departments=[],
            severity=None,
        )


# ---------------------------------------------------------------------------
# Mock answer generation
# ---------------------------------------------------------------------------


# The 8-phase rule-based flow splits into bulk phases (a whole form submitted
# at once) and sequential phases (one question per step, phases 4 & 7).
# Keeping the bulk set named avoids scattered `phase <= 3` magic numbers that
# silently rot when phases are inserted — e.g. phases 5 & 6 (past/personal
# history) are bulk but come *after* the sequential OLDCARTS phase 4.
_BULK_PHASES = frozenset({0, 1, 2, 3, 5, 6})


def generate_mock_answer(step: QuestionsStep) -> Any:
    """Produce a mock answer for the given QuestionsStep.

    When ``_random_mode`` is True, answers are randomised where possible.
    Otherwise falls back to the original deterministic strategy.

    The strategy varies by phase:
    - Phase 0 (Demographics):       hardcoded dict (or random from pool)
    - Phase 1 (ER Critical):        all False (or random True/False)
    - Phase 2 (Symptom Selection):  configurable primary symptom, no secondary
    - Phase 3 (ER Checklist):       all False (or random True/False)
    - Phases 5, 6 (Past/Personal History): bulk dict keyed by field key,
      auto-generated from each field's demographic type
    - Phases 4, 7 (OLDCARTS / OPD): sequential — auto-generate from question_type
    """
    phase = step.phase

    # --- Bulk phases: return a dict keyed by qid or field key ---

    if phase == 0:
        if _random_mode:
            return random.choice(_RANDOM_DEMOGRAPHICS_POOL)
        return MOCK_DEMOGRAPHICS

    if phase == 1:
        # --skip-er forces all False so the simulation never terminates here
        if _random_mode and not _skip_er:
            return {q.qid: random.choice([True, False]) for q in step.questions}
        return {q.qid: False for q in step.questions}

    if phase == 2:
        # primary_symptom is set by the caller; secondary_symptoms empty
        # This case is handled in the run loop where we have access to
        # the chosen symptom — it should not reach here.
        raise RuntimeError("Phase 2 answer is handled in the run loop")

    if phase == 3:
        if _random_mode and not _skip_er:
            return {q.qid: random.choice([True, False]) for q in step.questions}
        return {q.qid: False for q in step.questions}

    if phase in (5, 6):
        # Past/personal history — bulk, but (unlike phases 1 & 3) the
        # submission dict is keyed by each field's `key`, not its qid,
        # because these phases reuse the demographic-field schema.
        return {
            q.metadata["key"]: _answer_for_field_type(q)
            for q in step.questions
        }

    # --- Sequential phases (4, 7): exactly one question per step ---

    q = step.questions[0]
    return _answer_for_question_type(q)


def _answer_for_field_type(q) -> Any:
    """Pick a mock answer for a demographic-style bulk field (phases 0, 5, 6).

    These phases carry *demographic field types* (``int``, ``float``, ``enum``,
    ``str``, ``date``, ``yes_no_detail``, ``from_yaml``) — a different type
    vocabulary from the sequential-phase question types handled by
    ``_answer_for_question_type()``.

    Answers are deliberately "negative/minimal" (no, empty, first option) so
    they never activate conditional sub-fields the simulation has no schema to
    fill — e.g. answering ``yes_no_detail`` with ``yes`` would demand a
    ``detail`` object whose shape varies per field.
    """
    qtype = q.question_type

    if qtype == "yes_no_detail":
        # Always "no" — "yes" would require a detail_fields payload.
        return {"answer": False}

    if qtype == "enum":
        if q.options:
            if _random_mode:
                return random.choice(q.options)["id"]
            return q.options[0]["id"]
        return ""

    if qtype == "int":
        # Small positive int (these fields are counts/years) — 1 clears any
        # min/max range present on history fields.
        return random.randint(1, 5) if _random_mode else 1

    if qtype == "float":
        # Must be > 0 (engine rejects non-positive floats). Range loosely
        # covers both height (cm) and weight (kg) fields.
        return round(random.uniform(40.0, 180.0), 1) if _random_mode else 65.0

    if qtype in ("date", "datetime"):
        # A fixed past date — `datetime` fields additionally reject the future.
        return "2020-01-01"

    if qtype == "from_yaml":
        # List-valued field (e.g. underlying diseases) — empty list is valid.
        return []

    # `str` and any unexpected type fall back to free text.
    if _random_mode:
        return random.choice(_RANDOM_FREE_TEXT_POOL)
    return "ไม่มี"


def _answer_for_question_type(q) -> Any:
    """Pick an answer based on the question's type and schema.

    When ``_random_mode`` is True, answers are chosen randomly from the
    available options/range.  Otherwise uses the original deterministic
    strategy (first option, midpoint, etc.).
    """
    qtype = q.question_type

    if qtype == "free_text":
        if _random_mode:
            return random.choice(_RANDOM_FREE_TEXT_POOL)
        return "ไม่มี"

    if qtype == "free_text_with_fields":
        # Fields are stored as [{id, label, kind}, ...]
        if q.fields:
            if _random_mode:
                return {f["id"]: random.choice(_RANDOM_FREE_TEXT_POOL) for f in q.fields}
            return {f["id"]: "ไม่มี" for f in q.fields}
        if _random_mode:
            return random.choice(_RANDOM_FREE_TEXT_POOL)
        return "ไม่มี"

    if qtype == "number_range":
        constraints = q.constraints or {}
        lo = constraints.get("min", 0)
        hi = constraints.get("max", 10)
        if _random_mode:
            # Constraints may be floats (e.g. 0.0-10.0); use uniform for
            # float ranges, randint for int ranges.
            if isinstance(lo, float) or isinstance(hi, float):
                return round(random.uniform(lo, hi), 1)
            return random.randint(lo, hi)
        return (lo + hi) / 2

    if qtype in ("single_select", "image_single_select"):
        if q.options:
            if _random_mode:
                return random.choice(q.options)["id"]
            return q.options[0]["id"]
        return "unknown"

    if qtype in ("multi_select", "image_multi_select"):
        if q.options:
            if _random_mode:
                # Pick 1 to len(options) random options
                k = random.randint(1, len(q.options))
                chosen = random.sample(q.options, k)
                return [o["id"] for o in chosen]
            return [q.options[0]["id"]]
        return []

    # Fallback for any unexpected type
    if _random_mode:
        return random.choice(_RANDOM_FREE_TEXT_POOL)
    return "ไม่มี"


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

_DOUBLE_LINE = "\u2550" * 62
_SINGLE_LINE = "\u2500" * 62

# Module-level flags toggled by CLI args; checked by answer generators and
# log helpers respectively.
_random_mode = True
_skip_er = False
_quiet = False


def _print(*args, **kwargs) -> None:
    """Print wrapper that respects the --quiet flag."""
    if not _quiet:
        print(*args, **kwargs)


def log_phase_header(phase: int, phase_name: str, mode: str) -> None:
    """Print a bold header for a new phase."""
    _print(f"\n{_DOUBLE_LINE}")
    _print(f" PHASE {phase}: {phase_name} ({mode})")
    _print(_DOUBLE_LINE)


def log_pipeline_stage(stage_name: str) -> None:
    """Print a header for a pipeline-level stage (LLM, result)."""
    _print(f"\n{_DOUBLE_LINE}")
    _print(f" PIPELINE STAGE: {stage_name}")
    _print(_DOUBLE_LINE)


def log_transition(next_desc: str) -> None:
    """Print a transition marker showing what comes next."""
    _print(f"\n{_SINGLE_LINE}")
    _print(f" Submitted -> Next: {next_desc}")
    _print(_SINGLE_LINE)


def log_question_and_answer(
    q,
    answer: Any,
    *,
    prefix: str = "Q",
    verbose: bool = False,
) -> None:
    """Print a single question and its mock answer."""
    qtype = q.question_type
    qid = q.qid
    label = q.question

    _print(f"\n [{prefix}] {label} ({qid}) -- type: {qtype}")

    # Show options if available
    if q.options:
        option_labels = [o.get("label", o.get("id", "?")) for o in q.options]
        _print(f"     Options: {', '.join(option_labels)}")

    # Show fields for free_text_with_fields
    if q.fields:
        field_labels = [f.get("label", f.get("id", "?")) for f in q.fields]
        _print(f"     Fields: {', '.join(field_labels)}")

    # Show constraints for number_range
    if q.constraints:
        c = q.constraints
        _print(f"     Range: {c.get('min', '?')} - {c.get('max', '?')}")

    # Show the answer
    _print(f" [A] {answer}")

    # Verbose: include schemas
    if verbose:
        if q.answer_schema:
            _print(f"     answer_schema: {json.dumps(q.answer_schema, ensure_ascii=False)}")


def log_bulk_answers(step: QuestionsStep, answer: Any, *, verbose: bool = False) -> None:
    """Log all questions and answers for a bulk phase."""
    # For bulk phases, answer is a dict keyed either by field `key` or by qid.
    # Phases 0, 5, 6 reuse the demographic-field schema and are keyed by
    # `metadata["key"]`; the ER phases (1, 3) are keyed by qid.
    keyed_by_field = step.phase in (0, 5, 6)
    for q in step.questions:
        qid = q.qid
        if keyed_by_field:
            key = q.metadata.get("key", qid) if q.metadata else qid
            ans = answer.get(key, "--")
        else:
            ans = answer.get(qid, "--")
        log_question_and_answer(q, ans, verbose=verbose)

    if verbose and step.submission_schema:
        _print(f"\n     submission_schema: {json.dumps(step.submission_schema, ensure_ascii=False)}")


def log_opd_auto_eval_chain(
    store: RulesetStore,
    session_row: Any,
    *,
    verbose: bool = False,
) -> None:
    """Replay and log the OPD auto-eval chain that the engine evaluated internally.

    When Phase 5 is entirely conditional/filter questions, the engine processes
    them without returning any user-facing step.  This function re-runs the
    same evaluation logic and prints each auto-evaluated question, the rule
    that matched, and the resulting action so the simulation log is complete.
    """
    symptom = session_row.primary_symptom
    if not symptom:
        return

    # Build the same answers + demographics dicts the engine uses
    answers: dict[str, Any] = {}
    for qid, entry in session_row.responses.items():
        if qid.startswith("__"):
            continue
        if isinstance(entry, dict) and "value" in entry:
            answers[qid] = entry["value"]
        else:
            answers[qid] = entry

    demographics = dict(session_row.demographics or {})
    if "age" not in demographics:
        dob_str = demographics.get("date_of_birth")
        if dob_str:
            from datetime import date
            try:
                dob = date.fromisoformat(str(dob_str))
                today = date.today()
                age = today.year - dob.year
                if (today.month, today.day) < (dob.month, dob.day):
                    age -= 1
                demographics["age"] = age
            except (ValueError, TypeError):
                pass

    evaluator = ConditionalEvaluator()

    # Seed with the first OPD qid and walk the auto-eval chain
    try:
        first_qid = store.get_first_qid("opd", symptom)
    except KeyError:
        _print("\n (no OPD tree for this symptom)")
        return

    pending = [first_qid]
    step_num = 0

    while pending:
        qid = pending.pop(0)
        if qid in answers:
            continue

        try:
            question = store.get_question("opd", symptom, qid)
        except KeyError:
            continue

        if question.question_type not in AUTO_EVAL_TYPES:
            # User-facing question — would have been shown if reached
            break

        action = evaluator.evaluate(question, answers, demographics)
        step_num += 1

        # Format action description
        if action is None:
            action_desc = "no match (skipped)"
        elif isinstance(action, GotoAction):
            action_desc = f"goto -> {action.qid}"
        elif isinstance(action, TerminateAction):
            depts = action.department or []
            sevs = action.severity or []
            dept_str = ", ".join(depts) if depts else "none"
            sev_str = ", ".join(sevs) if sevs else "none"
            action_desc = f"terminate (dept={dept_str}, sev={sev_str})"
        else:
            action_desc = f"{action.action}"

        _print(f"\n [Auto {step_num}] {question.question} ({qid})"
               f" -- type: {question.question_type}")
        _print(f"           -> {action_desc}")

        if verbose and hasattr(question, "rules"):
            for i, rule in enumerate(question.rules, 1):
                predicates = ", ".join(
                    f"{p.qid} {p.op} {p.value}" for p in rule.when
                )
                _print(f"           rule {i}: when({predicates})")

        # Follow the chain
        if action is None:
            continue
        if isinstance(action, GotoAction):
            new_qids = [q for q in action.qid if q not in answers and q not in pending]
            pending[0:0] = new_qids
        elif isinstance(action, TerminateAction):
            break  # Chain terminated


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------


async def run_simulation(
    symptom: str,
    verbose: bool,
    quiet: bool = False,
    use_random: bool = True,
    skip_er: bool = False,
    disable_early_termination: bool = False,
) -> None:
    """Drive the full pipeline simulation and print audit logs.

    ``disable_early_termination`` is passed straight through to
    ``create_session``.  When set, the engine skips every early-exit point
    (ER phases 1 & 3, OLDCARTS/OPD terminates) and runs all 8 phases to
    completion — the only path that reaches ``_finalize_with_prediction``,
    so it is required to exercise the LLM prediction and disease-driven
    custom-reason stages.
    """
    global _quiet, _random_mode, _skip_er
    _quiet = quiet
    _random_mode = use_random
    _skip_er = skip_er

    # Suppress SDK logger output in quiet mode
    if quiet:
        logging.getLogger("prescreen_rulesets").setLevel(logging.CRITICAL)

    # --- Setup: load rulesets, create engine + pipeline with mocks ---
    store = RulesetStore()
    store.load()

    # When --random is active and no explicit symptom was given, pick one
    # at random from the available NHSO symptoms.
    if _random_mode and symptom == _DEFAULT_SYMPTOM:
        symptom = random.choice(list(store.nhso_symptoms.keys()))

    # Validate the chosen symptom exists
    if symptom not in store.nhso_symptoms:
        available = sorted(store.nhso_symptoms.keys())
        # Always print errors regardless of --quiet
        print(f"Error: Unknown symptom '{symptom}'.")
        print(f"Available symptoms: {', '.join(available)}")
        sys.exit(1)

    mock_repo = MockRepository()
    mock_db = AsyncMock()

    engine = PrescreenEngine(store)
    engine._repo = mock_repo

    pipeline = PrescreenPipeline(
        engine, store,
        generator=SimQuestionGenerator(),
        predictor=SimPredictionModule(),
    )
    pipeline._repo = mock_repo

    _print(f"{'=' * 62}")
    _print(f" PRESCREEN PIPELINE SIMULATION")
    _print(f" Symptom: {symptom}")
    _print(f" Random:  {'ON' if _random_mode else 'OFF'}")
    _print(f" Early termination: {'DISABLED' if disable_early_termination else 'enabled'}")
    _print(f"{'=' * 62}")

    # --- Phase 0: Demographics (bulk) ---
    await pipeline.create_session(
        mock_db, user_id=USER_ID, session_id=SESSION_ID,
        disable_early_termination=disable_early_termination,
    )
    step = await pipeline.get_current_step(mock_db, user_id=USER_ID, session_id=SESSION_ID)

    log_phase_header(0, step.phase_name, "bulk")
    answer = generate_mock_answer(step)
    log_bulk_answers(step, answer, verbose=verbose)

    step = await pipeline.submit_answer(
        mock_db, user_id=USER_ID, session_id=SESSION_ID, value=answer,
    )

    # --- Phases 1-7: adaptive loop ---
    # Each phase may trigger early termination (e.g. ER critical flags),
    # so we check the step type after every submission instead of asserting
    # a fixed phase sequence.
    seq_count = 0
    current_phase = None

    while isinstance(step, QuestionsStep):
        phase = step.phase

        # Print transition / phase header when the phase changes
        if phase != current_phase:
            current_phase = phase
            mode = "bulk" if phase in _BULK_PHASES else "sequential"
            log_transition(f"Phase {phase} ({step.phase_name})")
            log_phase_header(phase, step.phase_name, mode)

        # --- Build the answer for this step ---

        if phase == 2:
            # Symptom selection: use the chosen symptom
            answer = {"primary_symptom": symptom}
            for q in step.questions:
                if q.qid == "primary_symptom":
                    log_question_and_answer(q, symptom, verbose=verbose)
                else:
                    log_question_and_answer(q, "[]", verbose=verbose)
            if verbose and step.submission_schema:
                _print(f"\n     submission_schema: {json.dumps(step.submission_schema, ensure_ascii=False)}")

        elif phase in _BULK_PHASES:
            # Bulk phases (1, 3, 5, 6): generate_mock_answer returns the
            # whole-form dict and handles randomisation.
            answer = generate_mock_answer(step)
            log_bulk_answers(step, answer, verbose=verbose)

        else:
            # Sequential phases (4, 7): one question per step
            q = step.questions[0]
            answer = _answer_for_question_type(q)
            log_question_and_answer(q, answer, verbose=verbose)
            if verbose and step.submission_schema:
                _print(f"     submission_schema: {json.dumps(step.submission_schema, ensure_ascii=False)}")
            seq_count += 1

        step = await pipeline.submit_answer(
            mock_db, user_id=USER_ID, session_id=SESSION_ID, value=answer,
        )

    # --- Post-rule-based: log OPD if it was auto-evaluated ---
    # When OPD (phase 7) is entirely conditional/filter questions, no user-facing
    # QuestionsStep is returned, so the loop above never logs Phase 7.  Check the
    # session state to detect this and print an informational header.
    if current_phase != 7:
        session_row = await mock_repo.get_by_user_and_session(mock_db, USER_ID, SESSION_ID)
        if session_row and session_row.current_phase >= 7:
            log_transition("Phase 7 (OPD)")
            log_phase_header(7, "OPD", "auto-evaluated")
            log_opd_auto_eval_chain(store, session_row, verbose=verbose)

    # --- Post-rule-based: check what the pipeline returned ---

    if isinstance(step, LLMQuestionsStep):
        # Pipeline generated LLM follow-up questions
        log_pipeline_stage("llm_questioning")

        # Build answers — random from pool or pre-canned
        chosen_llm_answers: list[str] = []
        for i, question in enumerate(step.questions, 1):
            if _random_mode:
                mock_answer = random.choice(_RANDOM_LLM_ANSWER_POOL)
            else:
                mock_answer = MOCK_LLM_ANSWERS[i - 1] if i <= len(MOCK_LLM_ANSWERS) else "ไม่ทราบ"
            chosen_llm_answers.append(mock_answer)
            _print(f"\n [LLM Q{i}] {question}")
            _print(f" [LLM A{i}] {mock_answer}")

        # Submit the LLM answers
        llm_answers = [
            LLMAnswer(question=q, answer=chosen_llm_answers[i])
            for i, q in enumerate(step.questions)
        ]

        result = await pipeline.submit_llm_answers(
            mock_db, user_id=USER_ID, session_id=SESSION_ID,
            answers=llm_answers,
        )
    elif isinstance(step, PipelineResult):
        # Pipeline skipped LLM or went straight to result (e.g. early termination)
        result = step
    elif isinstance(step, TerminationStep):
        # Engine-level early termination (ER redirect) — build a minimal result
        log_pipeline_stage("EARLY TERMINATION")
        _print(f"\n Terminated at phase {step.phase}: {step.reason or '(no reason)'}")
        result = PipelineResult(
            departments=step.departments,
            severity=step.severity,
            diagnoses=[],
            reason=step.reason,
            terminated_early=True,
        )
    else:
        # Unexpected step type — log it
        _print(f"\n [!] Unexpected step type: {type(step).__name__}")
        _print(f"     {step}")
        return

    # --- Final result ---

    log_pipeline_stage("RESULT")

    # Departments
    if result.departments:
        dept_strs = [f"{d.get('name', '?')} ({d.get('id', '?')})" for d in result.departments]
        _print(f"\n Departments: {', '.join(dept_strs)}")
    else:
        _print("\n Departments: (none)")

    # Severity
    if result.severity:
        sev = result.severity
        _print(f" Severity:    {sev.get('name', '?')} ({sev.get('id', '?')})")
    else:
        _print(" Severity:    (none)")

    # Diagnoses — DiagnosisResult exposes only disease_id (ranked most-likely
    # first); no confidence score is surfaced, by design, to avoid clinical
    # misinterpretation.
    if result.diagnoses:
        dx_strs = [d.disease_id for d in result.diagnoses]
        _print(f" Diagnoses:   {', '.join(dx_strs)}")
    else:
        _print(" Diagnoses:   (none)")

    # Terminated early?
    _print(f" Terminated:  {'Yes' if result.terminated_early else 'No'}")

    # Reason
    if result.reason:
        _print(f" Reason:      {result.reason}")

    _print(f"\n{'=' * 62}")
    _print(f" Simulation complete ({seq_count} sequential questions answered)")
    _print(f"{'=' * 62}")


def list_symptoms(store: RulesetStore) -> None:
    """Print all available NHSO symptoms and exit."""
    print("Available NHSO symptoms:")
    print()
    for i, (name, sym) in enumerate(sorted(store.nhso_symptoms.items()), 1):
        print(f"  {i:2d}. {name:<25s} ({sym.name_th})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simulate the PrescreenPipeline end-to-end with mocked DB and LLM.",
    )
    parser.add_argument(
        "-s", "--symptom",
        default=_DEFAULT_SYMPTOM,
        help="Primary symptom to simulate (default: Headache). "
             "When --random is on and no symptom is specified, a random one is chosen.",
    )
    parser.add_argument(
        "--list-symptoms",
        action="store_true",
        help="List all available NHSO symptoms and exit",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Include submission_schema and answer_schema in logs",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress all print output (exit code still reflects success/failure)",
    )
    parser.add_argument(
        "--random",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Randomise mock answers (default: on). Use --no-random for deterministic mode.",
    )
    parser.add_argument(
        "--skip-er",
        action="store_true",
        default=False,
        help="Force all ER answers to False (phases 1 & 3) to skip early termination.",
    )
    parser.add_argument(
        "--disable-early-termination",
        action="store_true",
        default=False,
        help="Pass disable_early_termination=True to create_session so the engine "
             "runs all 8 phases to completion. This is the only way the simulation "
             "reaches the LLM prediction + disease-reason stages (the rule-based "
             "trees otherwise terminate well before phase 7).",
    )
    args = parser.parse_args()

    if args.list_symptoms:
        store = RulesetStore()
        store.load()
        list_symptoms(store)
        sys.exit(0)

    asyncio.run(run_simulation(
        args.symptom, args.verbose, args.quiet, args.random, args.skip_er,
        args.disable_early_termination,
    ))


if __name__ == "__main__":
    main()
