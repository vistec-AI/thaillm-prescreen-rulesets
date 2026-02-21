"""prescreen_rulesets — Rule-based prescreening SDK.

Public API:
    PrescreenEngine   — main orchestrator for the 6-phase prescreening flow
    PrescreenPipeline — full pipeline orchestrator (engine + LLM + prediction)
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

Pipeline step models:
    LLMAnswer         — input for submit_llm_answers
    LLMQuestionsStep  — step: LLM-generated follow-up questions
    PipelineResult    — step: final result with DDx, department, severity
    PipelineStep      — union of all pipeline step types
"""

from prescreen_rulesets.engine import PrescreenEngine
from prescreen_rulesets.interfaces import PredictionModule, QuestionGenerator
from prescreen_rulesets.models.pipeline import (
    DiagnosisResult,
    GeneratedQuestions,
    LLMAnswer,
    LLMQuestionsStep,
    PipelineResult,
    PipelineStep,
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
from prescreen_rulesets.pipeline import PrescreenPipeline
from prescreen_rulesets.prompt import PromptManager
from prescreen_rulesets.ruleset import RulesetStore

__all__ = [
    # Engine & store
    "PrescreenEngine",
    "PrescreenPipeline",
    "PromptManager",
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
    "LLMAnswer",
    "LLMQuestionsStep",
    "PipelineResult",
    "PipelineStep",
]
