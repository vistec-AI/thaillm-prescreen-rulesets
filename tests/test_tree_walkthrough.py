"""Fuzz test: random user walks through every symptom's OLDCARTS and OPD trees.

For every NHSO symptom, simulates a user traversing the decision tree by
picking random valid answers.  Verifies that:

  1. The walk always terminates (no infinite loops)
  2. Every question encountered is a valid type
  3. Every action resolves to a valid target
  4. OLDCARTS trees end with 'opd' (→ switch to OPD) or 'terminate'
  5. OPD trees end with 'terminate'

Random choices use fixed seeds (``random.Random(seed)``) for reproducibility.
OPD walkthroughs seed prior answers from an OLDCARTS walk so conditional
predicates referencing OLDCARTS qids have values to evaluate against.
"""

import random

import pytest

from prescreen_rulesets.constants import AUTO_EVAL_TYPES
from prescreen_rulesets.evaluator import ConditionalEvaluator
from prescreen_rulesets.models.action import GotoAction, OPDAction, TerminateAction
from prescreen_rulesets.models.question import (
    FreeTextQuestion,
    FreeTextWithFieldQuestion,
    ImageMultiSelectQuestion,
    ImageSelectQuestion,
    MultiSelectQuestion,
    NumberRangeQuestion,
    SingleSelectQuestion,
)
from prescreen_rulesets.ruleset import RulesetStore

# Number of random walk iterations per symptom per demographic combo.
# Higher values explore more paths but take longer.
NUM_RANDOM_RUNS = 100

# Safety limit to detect infinite loops (a real tree should finish well
# under 100 steps).
MAX_STEPS = 1_000


@pytest.fixture(scope="session")
def store():
    """Load the full RulesetStore once for the entire test session."""
    s = RulesetStore()
    s.load()
    return s


# Static list of all 16 NHSO symptoms (must match v1/const/nhso_symptoms.yaml).
ALL_SYMPTOMS = [
    "Headache",
    "Dizziness",
    "Pain in Joint",
    "Muscle Pain",
    "Fever",
    "Cough",
    "Sore Throat",
    "Stomachache",
    "Constipation",
    "Diarrhea",
    "Dysuria",
    "Vaginal Discharge",
    "Skin Rash/Lesion",
    "Wound",
    "Eye Disorder",
    "Ear Disorder",
]


# =====================================================================
# Helper functions
# =====================================================================


def _random_answer(rng, question):
    """Generate a plausible random answer for any user-facing question type.

    The answer type matches what a real user would submit for each question
    type so that action resolution works correctly.
    """
    if isinstance(question, FreeTextQuestion):
        return "random text"

    if isinstance(question, FreeTextWithFieldQuestion):
        return {f.id: "text" for f in question.fields}

    if isinstance(question, NumberRangeQuestion):
        return rng.uniform(question.min_value, question.max_value)

    if isinstance(question, (SingleSelectQuestion, ImageSelectQuestion)):
        return rng.choice(question.options).id

    if isinstance(question, (MultiSelectQuestion, ImageMultiSelectQuestion)):
        k = rng.randint(1, len(question.options))
        return [o.id for o in rng.sample(question.options, k)]

    raise ValueError(f"Unexpected question type: {question.question_type}")


def _determine_action(question, value):
    """Determine the resulting action based on question type and user answer.

    Mirrors PrescreenEngine._determine_action logic without the engine
    dependency.
    """
    if isinstance(question, (SingleSelectQuestion, ImageSelectQuestion)):
        # value is the selected option ID — find the matching option
        for opt in question.options:
            if opt.id == value:
                return opt.action
        return None

    if isinstance(question, (MultiSelectQuestion, ImageMultiSelectQuestion)):
        # Multi-select always uses the question's "next" action
        return question.next

    if isinstance(question, (FreeTextQuestion, FreeTextWithFieldQuestion,
                              NumberRangeQuestion)):
        return question.on_submit

    return None


def _walk_tree(store, evaluator, source, symptom, demographics, rng,
               prior_answers=None):
    """Walk a decision tree from start to a terminal action.

    Simulates the engine's sequential phase logic: pop qids from a pending
    queue, auto-evaluate filter/conditional questions, and generate random
    answers for user-facing questions.

    Args:
        store: loaded RulesetStore
        evaluator: ConditionalEvaluator instance
        source: "oldcarts" or "opd"
        symptom: symptom name (e.g. "Headache")
        demographics: dict with age, gender, etc.
        rng: seeded random.Random instance
        prior_answers: answers from a prior phase (e.g. OLDCARTS → OPD)

    Returns:
        (terminal_type, steps, answers) where terminal_type is
        "opd", "terminate", or "exhausted"
    """
    # Carry forward any prior answers (OPD needs OLDCARTS answers for
    # conditional predicates that reference OLDCARTS qids)
    answers = dict(prior_answers) if prior_answers else {}
    pending = [store.get_first_qid(source, symptom)]
    steps = 0

    while pending and steps < MAX_STEPS:
        qid = pending.pop(0)

        # Skip already-answered questions (de-duplication)
        if qid in answers:
            continue

        question = store.get_question(source, symptom, qid)
        steps += 1

        # --- Auto-eval types (gender_filter, age_filter, conditional) ---
        if question.question_type in AUTO_EVAL_TYPES:
            action = evaluator.evaluate(question, answers, demographics)
            if action is None:
                # No rule matched and no default — skip this question
                continue
        else:
            # --- User-facing question: generate random answer ---
            value = _random_answer(rng, question)
            answers[qid] = value
            action = _determine_action(question, value)

            if action is None:
                # Could not determine action — continue with pending
                continue

        # --- Process action ---
        if isinstance(action, GotoAction):
            # Add goto targets to front of pending, skip already-answered
            new_qids = [q for q in action.qid
                        if q not in answers and q not in pending]
            pending[0:0] = new_qids
        elif isinstance(action, OPDAction):
            return ("opd", steps, answers)
        elif isinstance(action, TerminateAction):
            return ("terminate", steps, answers)

    assert steps < MAX_STEPS, (
        f"Possible infinite loop in {source}/{symptom} after {steps} steps"
    )
    return ("exhausted", steps, answers)


# =====================================================================
# OLDCARTS walkthrough tests
# =====================================================================


@pytest.mark.parametrize("symptom", ALL_SYMPTOMS)
def test_oldcarts_walkthrough_adult(store, symptom):
    """OLDCARTS tree for an adult reaches opd or terminate without error."""
    demographics = {"age": 30, "gender": "male"}
    evaluator = ConditionalEvaluator()

    for seed in range(NUM_RANDOM_RUNS):
        rng = random.Random(seed)
        result, steps, _ = _walk_tree(
            store, evaluator, "oldcarts", symptom, demographics, rng,
        )
        assert result in ("opd", "terminate"), (
            f"Unexpected result '{result}' for {symptom} "
            f"(seed={seed}, steps={steps})"
        )


@pytest.mark.parametrize("symptom", ALL_SYMPTOMS)
def test_oldcarts_walkthrough_pediatric(store, symptom):
    """OLDCARTS tree for a child reaches opd or terminate without error."""
    demographics = {"age": 10, "gender": "female"}
    evaluator = ConditionalEvaluator()

    for seed in range(NUM_RANDOM_RUNS):
        rng = random.Random(seed)
        result, steps, _ = _walk_tree(
            store, evaluator, "oldcarts", symptom, demographics, rng,
        )
        assert result in ("opd", "terminate"), (
            f"Unexpected result '{result}' for {symptom} "
            f"(seed={seed}, steps={steps})"
        )


# =====================================================================
# OPD walkthrough tests
# =====================================================================


@pytest.mark.parametrize("symptom", ALL_SYMPTOMS)
def test_opd_walkthrough_adult(store, symptom):
    """OPD tree for an adult reaches terminate without error.

    Seeds answers from a prior OLDCARTS walk so conditional predicates
    referencing OLDCARTS qids have values to evaluate against.
    """
    demographics = {"age": 30, "gender": "male"}
    evaluator = ConditionalEvaluator()

    for seed in range(NUM_RANDOM_RUNS):
        rng = random.Random(seed)
        # Walk OLDCARTS first to collect answers
        _, _, oldcarts_answers = _walk_tree(
            store, evaluator, "oldcarts", symptom, demographics, rng,
        )
        # Walk OPD with OLDCARTS answers available
        result, steps, _ = _walk_tree(
            store, evaluator, "opd", symptom, demographics, rng,
            prior_answers=oldcarts_answers,
        )
        assert result == "terminate", (
            f"OPD should terminate, got '{result}' for {symptom} "
            f"(seed={seed}, steps={steps})"
        )


@pytest.mark.parametrize("symptom", ALL_SYMPTOMS)
def test_opd_walkthrough_pediatric(store, symptom):
    """OPD tree for a child reaches terminate without error."""
    demographics = {"age": 10, "gender": "female"}
    evaluator = ConditionalEvaluator()

    for seed in range(NUM_RANDOM_RUNS):
        rng = random.Random(seed)
        _, _, oldcarts_answers = _walk_tree(
            store, evaluator, "oldcarts", symptom, demographics, rng,
        )
        result, steps, _ = _walk_tree(
            store, evaluator, "opd", symptom, demographics, rng,
            prior_answers=oldcarts_answers,
        )
        assert result == "terminate", (
            f"OPD should terminate, got '{result}' for {symptom} "
            f"(seed={seed}, steps={steps})"
        )


# =====================================================================
# Full flow walkthrough (OLDCARTS → OPD)
# =====================================================================


@pytest.mark.parametrize("symptom", ALL_SYMPTOMS)
def test_full_flow_walkthrough(store, symptom):
    """Full OLDCARTS → OPD flow for a symptom always terminates.

    Walks OLDCARTS to completion, then walks OPD with the accumulated
    answers.  Tests both adult and pediatric demographics.
    """
    evaluator = ConditionalEvaluator()

    for age, gender in [(30, "male"), (10, "female")]:
        demographics = {"age": age, "gender": gender}

        for seed in range(NUM_RANDOM_RUNS):
            rng = random.Random(seed)

            # Phase 4: OLDCARTS
            oc_result, _, oc_answers = _walk_tree(
                store, evaluator, "oldcarts", symptom, demographics, rng,
            )

            if oc_result == "terminate":
                # OLDCARTS terminated early (e.g. severe case → ER redirect)
                continue

            assert oc_result == "opd", (
                f"OLDCARTS should end with 'opd' or 'terminate', "
                f"got '{oc_result}' for {symptom}"
            )

            # Phase 5: OPD (with OLDCARTS answers carried forward)
            opd_result, _, _ = _walk_tree(
                store, evaluator, "opd", symptom, demographics, rng,
                prior_answers=oc_answers,
            )
            assert opd_result == "terminate", (
                f"OPD should terminate, got '{opd_result}' for {symptom} "
                f"(age={age}, gender={gender}, seed={seed})"
            )
