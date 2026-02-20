"""prescreen_rulesets — Rule-based prescreening SDK.

Public API:
    PrescreenEngine  — main orchestrator for the 6-phase prescreening flow
    RulesetStore     — loads YAML rulesets into typed models with lookup helpers
    StepResult       — union type returned by engine step methods
    QuestionsStep    — step: present questions to the user
    TerminationStep  — step: session ended with a result
    SessionInfo      — public view of session state
"""

from prescreen_rulesets.engine import PrescreenEngine
from prescreen_rulesets.ruleset import RulesetStore
from prescreen_rulesets.models.session import (
    QuestionPayload,
    QuestionsStep,
    SessionInfo,
    StepResult,
    TerminationStep,
)

__all__ = [
    "PrescreenEngine",
    "RulesetStore",
    "QuestionPayload",
    "QuestionsStep",
    "SessionInfo",
    "StepResult",
    "TerminationStep",
]
