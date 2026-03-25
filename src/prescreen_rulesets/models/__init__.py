"""Public model re-exports for prescreen_rulesets.

Consumers should import from ``prescreen_rulesets.models`` rather than
reaching into sub-modules directly.
"""

# --- Actions ---
from prescreen_rulesets.models.action import (
    Action,
    DepartmentRef,
    GotoAction,
    OPDAction,
    SeverityRef,
    TerminateAction,
    TerminateMetadata,
)

# --- Questions ---
from prescreen_rulesets.models.question import (
    AgeFilterQuestion,
    BaseQuestion,
    ConditionalQuestion,
    FreeTextQuestion,
    FreeTextWithFieldQuestion,
    GenderQuestion,
    ImageMultiSelectQuestion,
    ImageSelectQuestion,
    MultiSelectQuestion,
    NumberRangeQuestion,
    Predicate,
    Question,
    Rule,
    SingleSelectQuestion,
    question_mapper,
)

# --- Schema / constants ---
from prescreen_rulesets.models.schema import (
    Department,
    DepartmentConst,
    DemographicField,
    DetailField,
    Disease,
    ERChecklistItem,
    ERCriticalItem,
    FieldCondition,
    NHSOSymptom,
    NHSOSymptoms,
    SeverityConst,
    SeverityLevel,
    UnderlyingDisease,
    UnderlyingDiseaseSubType,
)

# --- Session / step ---
from prescreen_rulesets.models.session import (
    QuestionPayload,
    QuestionsStep,
    SessionInfo,
    SkippedTermination,
    StepResult,
    TerminationStep,
)

# --- Pipeline (post-rule-based stages) ---
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

__all__ = [
    # Actions
    "Action",
    "DepartmentRef",
    "GotoAction",
    "OPDAction",
    "SeverityRef",
    "TerminateAction",
    "TerminateMetadata",
    # Questions
    "AgeFilterQuestion",
    "BaseQuestion",
    "ConditionalQuestion",
    "FreeTextQuestion",
    "FreeTextWithFieldQuestion",
    "GenderQuestion",
    "ImageMultiSelectQuestion",
    "ImageSelectQuestion",
    "MultiSelectQuestion",
    "NumberRangeQuestion",
    "Predicate",
    "Question",
    "Rule",
    "SingleSelectQuestion",
    "question_mapper",
    # Schema
    "Department",
    "DepartmentConst",
    "DemographicField",
    "DetailField",
    "Disease",
    "ERChecklistItem",
    "ERCriticalItem",
    "FieldCondition",
    "NHSOSymptom",
    "NHSOSymptoms",
    "SeverityConst",
    "SeverityLevel",
    "UnderlyingDisease",
    "UnderlyingDiseaseSubType",
    # Session
    "QuestionPayload",
    "QuestionsStep",
    "SessionInfo",
    "SkippedTermination",
    "StepResult",
    "TerminationStep",
    # Pipeline
    "DiagnosisResult",
    "GeneratedQuestions",
    "LLMAnswer",
    "LLMQuestionsStep",
    "PipelineResult",
    "PipelineStep",
    "PredictionResult",
    "QAPair",
]
