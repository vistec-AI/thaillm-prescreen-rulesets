"""prescreen_rulesets — Rule-based prescreening SDK.

Public API:
    PrescreenEngine   — main orchestrator for the 6-phase prescreening flow
    RulesetStore      — loads YAML rulesets into typed models with lookup helpers
    StepResult        — union type returned by engine step methods
    QuestionsStep     — step: present questions to the user
    TerminationStep   — step: session ended with a result
    SessionInfo       — public view of session state

Pipeline interfaces (post-rule-based stages):
    QuestionGenerator — ABC for LLM-based follow-up question generation
    PredictionModule  — ABC for the diagnostic prediction head
    QAPair            — structured question-answer record shared across stages
    GeneratedQuestions — output wrapper for the question generator
    PredictionResult  — output of the prediction module
    DiagnosisResult   — single disease entry in the DDx output
"""

from prescreen_rulesets.engine import PrescreenEngine
from prescreen_rulesets.interfaces import PredictionModule, QuestionGenerator
from prescreen_rulesets.models.pipeline import (
    DiagnosisResult,
    GeneratedQuestions,
    PredictionResult,
    QAPair,
)
from prescreen_rulesets.models.session import (
    QuestionPayload,
    QuestionsStep,
    SessionInfo,
    StepResult,
    TerminationStep,
)
from prescreen_rulesets.ruleset import RulesetStore

__all__ = [
    # Engine & store
    "PrescreenEngine",
    "RulesetStore",
    # Session / step
    "QuestionPayload",
    "QuestionsStep",
    "SessionInfo",
    "StepResult",
    "TerminationStep",
    # Pipeline interfaces
    "QuestionGenerator",
    "PredictionModule",
    # Pipeline data models
    "QAPair",
    "GeneratedQuestions",
    "PredictionResult",
    "DiagnosisResult",
]
