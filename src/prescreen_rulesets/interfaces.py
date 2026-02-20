"""Abstract interfaces for post-rule-based pipeline stages.

These ABCs define the contract that external implementations must fulfil.
The SDK ships no concrete implementations — they live in separate packages
that are still under development.

Typical integration flow::

    engine = PrescreenEngine(store)
    # ... run the 6-phase rule-based flow, collect answers ...

    qa_pairs: list[QAPair] = ...  # build from session responses

    # Stage 1 — LLM follow-up questions
    generator: QuestionGenerator = MyLLMQuestionGenerator(...)
    generated = await generator.generate(qa_pairs)
    # ... present generated.questions to the patient, collect answers ...

    # Stage 2 — Prediction
    predictor: PredictionModule = MyPredictionModule(...)
    all_pairs = qa_pairs + llm_qa_pairs  # combine both sources
    result = await predictor.predict(all_pairs)
    # result.diagnoses, result.departments, result.severity
"""

from abc import ABC, abstractmethod

from prescreen_rulesets.models.pipeline import (
    GeneratedQuestions,
    PredictionResult,
    QAPair,
)


class QuestionGenerator(ABC):
    """Interface for LLM-based follow-up question generation.

    Implementations receive the structured Q&A history from the rule-based
    prescreening flow and return additional questions to gather more
    diagnostic detail from the patient.

    The SDK imposes no constraints on *how* the LLM generates questions;
    only the input/output contract is specified here.
    """

    @abstractmethod
    async def generate(self, qa_pairs: list[QAPair]) -> GeneratedQuestions:
        """Generate follow-up questions from rule-based Q&A history.

        Parameters
        ----------
        qa_pairs:
            Ordered list of question-answer pairs collected during the
            rule-based prescreening phases.  Each pair carries its source
            metadata (qid, phase, question_type) so the LLM can use
            contextual information for better question generation.

        Returns
        -------
        GeneratedQuestions
            A wrapper containing the list of natural-language question
            strings to present to the patient.
        """
        ...


class PredictionModule(ABC):
    """Interface for the diagnostic prediction head.

    Implementations receive *all* Q&A pairs — from both the rule-based
    flow and the LLM-generated follow-ups — and produce three outputs:

      1. Differential diagnosis (bounded by ``v1/const/diseases.yaml``)
      2. Department routing (bounded by ``v1/const/departments.yaml``)
      3. Severity assessment (bounded by ``v1/const/severity_levels.yaml``)
    """

    @abstractmethod
    async def predict(self, qa_pairs: list[QAPair]) -> PredictionResult:
        """Run prediction on the combined Q&A history.

        Parameters
        ----------
        qa_pairs:
            Ordered list of question-answer pairs from *both* the
            rule-based flow (``source="rule_based"``) and the LLM
            follow-up stage (``source="llm_generated"``).

        Returns
        -------
        PredictionResult
            Predicted diagnoses, departments, and severity.
        """
        ...
