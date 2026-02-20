"""PrescreenPipeline — orchestrates the full prescreening flow.

Wraps the rule-based ``PrescreenEngine`` and extends it with two optional
post-rule-based stages:

  1. **LLM Question Generator** — produces follow-up questions from the
     rule-based Q&A history.
  2. **Prediction Module** — consumes all Q&A pairs (rule-based + LLM) and
     outputs differential diagnosis, department routing, and severity.

The pipeline is **non-invasive to the engine**: it delegates to the engine
during the ``rule_based`` stage and takes over when the engine signals
completion or termination.  ``engine.py`` is never modified.

Pipeline stages (tracked by ``pipeline_stage`` column):

    rule_based ──► llm_questioning ──► done
                │                        ▲
                └──── (early exit) ──────┘

Usage::

    engine = PrescreenEngine(store)
    pipeline = PrescreenPipeline(
        engine, store,
        generator=MyQuestionGenerator(),
        predictor=MyPredictionModule(),
    )

    # Create session (same API as engine)
    info = await pipeline.create_session(db, user_id="u1", session_id="s1")

    # Rule-based phase — pipeline proxies to engine
    step = await pipeline.get_current_step(db, user_id="u1", session_id="s1")
    step = await pipeline.submit_answer(db, user_id="u1", session_id="s1",
                                         qid="demographics", value={...})
    # ... eventually engine signals completion ...

    # If LLM questions are generated:
    # step.type == "llm_questions"
    # step.questions == ["What is the pain intensity?", ...]

    # Submit LLM answers
    result = await pipeline.submit_llm_answers(
        db, user_id="u1", session_id="s1",
        answers=[LLMAnswer(question="...", answer="..."), ...],
    )
    # result.type == "pipeline_result"
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from prescreen_db.models.enums import PipelineStage, SessionStatus
from prescreen_db.models.session import PrescreenSession
from prescreen_db.repository import SessionRepository

from prescreen_rulesets.constants import AUTO_EVAL_TYPES, PEDIATRIC_AGE_THRESHOLD
from prescreen_rulesets.engine import PrescreenEngine
from prescreen_rulesets.interfaces import PredictionModule, QuestionGenerator
from prescreen_rulesets.models.pipeline import (
    DiagnosisResult,
    LLMAnswer,
    LLMQuestionsStep,
    PipelineResult,
    PipelineStep,
    QAPair,
)
from prescreen_rulesets.models.session import (
    QuestionsStep,
    SessionInfo,
    TerminationStep,
)
from prescreen_rulesets.ruleset import RulesetStore

logger = logging.getLogger(__name__)


class PrescreenPipeline:
    """Orchestrates the full prescreening pipeline.

    Manages the flow: rule-based engine -> LLM question generation -> prediction.
    The pipeline wraps the engine, checks ``pipeline_stage`` before delegating,
    and takes over when the engine signals completion or termination.

    Args:
        engine: a configured :class:`PrescreenEngine` instance
        store: the :class:`RulesetStore` backing the engine (used for Q&A
            reconstruction and department/severity resolution)
        generator: optional LLM question generator; if ``None``, the pipeline
            skips the LLM questioning stage entirely
        predictor: optional prediction module; if ``None``, the pipeline
            returns results without differential diagnosis
    """

    def __init__(
        self,
        engine: PrescreenEngine,
        store: RulesetStore,
        generator: QuestionGenerator | None = None,
        predictor: PredictionModule | None = None,
    ) -> None:
        self._engine = engine
        self._store = store
        self._generator = generator
        self._predictor = predictor
        self._repo = SessionRepository()

    # ==================================================================
    # Session lifecycle — proxy to engine
    # ==================================================================

    async def create_session(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: str,
        ruleset_version: str | None = None,
    ) -> SessionInfo:
        """Create a new prescreening session.

        Delegates to the engine.  The ``pipeline_stage`` column defaults to
        ``rule_based`` via the DB server_default, so no extra write is needed.
        """
        return await self._engine.create_session(
            db, user_id=user_id, session_id=session_id,
            ruleset_version=ruleset_version,
        )

    # ==================================================================
    # Step API
    # ==================================================================

    async def get_current_step(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: str,
    ) -> PipelineStep:
        """Return the current step, dispatching by ``pipeline_stage``.

        - ``rule_based``: delegate to engine's ``get_current_step``
        - ``llm_questioning``: return the stored LLM questions
        - ``done``: return the cached pipeline result
        """
        row = await self._load_session(db, user_id, session_id)
        stage = row.pipeline_stage

        if stage == PipelineStage.RULE_BASED.value:
            return await self._engine.get_current_step(
                db, user_id=user_id, session_id=session_id,
            )
        elif stage == PipelineStage.LLM_QUESTIONING.value:
            # Return the stored LLM questions for the user to answer
            questions = row.llm_questions or []
            return LLMQuestionsStep(questions=questions)
        elif stage == PipelineStage.DONE.value:
            return self._build_pipeline_result(row)
        else:
            raise ValueError(f"Unknown pipeline_stage: {stage}")

    async def submit_answer(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: str,
        qid: str,
        value: Any,
    ) -> PipelineStep:
        """Submit an answer during the rule-based stage.

        Delegates to the engine and handles the transition when the engine
        signals completion or termination.

        Raises:
            ValueError: if the session is not in the ``rule_based`` stage
        """
        row = await self._load_session(db, user_id, session_id)
        stage = row.pipeline_stage

        if stage != PipelineStage.RULE_BASED.value:
            raise ValueError(
                f"submit_answer is only valid during rule_based stage, "
                f"but session is in '{stage}'"
            )

        # Delegate to the engine
        step = await self._engine.submit_answer(
            db, user_id=user_id, session_id=session_id, qid=qid, value=value,
        )

        # If the engine returned a QuestionsStep, we're still in rule-based
        if isinstance(step, QuestionsStep):
            return step

        # Engine returned a TerminationStep — the rule-based phase is over.
        # Reload the session row to pick up engine mutations.
        row = await self._load_session(db, user_id, session_id)
        return await self._handle_rule_based_end(db, row, step)

    async def submit_llm_answers(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: str,
        answers: list[LLMAnswer],
    ) -> PipelineResult:
        """Submit answers to LLM-generated questions.

        Stores the answers, runs prediction (if available), and transitions
        the session to the ``done`` stage.

        Raises:
            ValueError: if the session is not in the ``llm_questioning`` stage
        """
        row = await self._load_session(db, user_id, session_id)
        stage = row.pipeline_stage

        if stage != PipelineStage.LLM_QUESTIONING.value:
            raise ValueError(
                f"submit_llm_answers is only valid during llm_questioning stage, "
                f"but session is in '{stage}'"
            )

        # Store the LLM answers
        response_dicts = [a.model_dump() for a in answers]
        await self._repo.save_llm_responses(db, row, response_dicts)

        # Build the full Q&A list: rule-based + LLM pairs
        rule_based_pairs = self._build_qa_pairs(row)
        llm_pairs = [
            QAPair(
                question=a.question,
                answer=a.answer,
                source="llm_generated",
            )
            for a in answers
        ]
        all_pairs = rule_based_pairs + llm_pairs

        # Run prediction if available
        await self._finalize_with_prediction(db, row, all_pairs)

        # Transition to done
        await self._repo.set_pipeline_stage(db, row, PipelineStage.DONE)

        return self._build_pipeline_result(row)

    # ==================================================================
    # Internal: rule-based end handling
    # ==================================================================

    async def _handle_rule_based_end(
        self,
        db: AsyncSession,
        row: PrescreenSession,
        step: TerminationStep,
    ) -> PipelineStep:
        """Handle the transition when the rule-based engine finishes.

        Two cases:
          - TERMINATED (ER early exit): skip LLM/prediction, return empty DDx
          - COMPLETED (all 6 phases done): proceed to LLM questioning or prediction
        """
        if row.status == SessionStatus.TERMINATED:
            # Early termination — add empty diagnoses to result, skip LLM/prediction
            result = row.result or {}
            result["diagnoses"] = []
            row.result = result
            await db.flush()

            await self._repo.set_pipeline_stage(db, row, PipelineStage.DONE)

            return PipelineResult(
                departments=[
                    self._store.resolve_department(d)
                    for d in (result.get("departments") or [])
                ],
                severity=(
                    self._store.resolve_severity(result["severity"])
                    if result.get("severity")
                    else None
                ),
                diagnoses=[],
                reason=result.get("reason") or row.termination_reason,
                terminated_early=True,
            )

        # COMPLETED — rule-based flow finished normally
        rule_based_pairs = self._build_qa_pairs(row)

        # Try LLM question generation if generator is available
        if self._generator is not None:
            generated = await self._generator.generate(rule_based_pairs)
            if generated.questions:
                # Store questions and transition to llm_questioning
                await self._repo.save_llm_questions(db, row, generated.questions)
                await self._repo.set_pipeline_stage(
                    db, row, PipelineStage.LLM_QUESTIONING,
                )
                return LLMQuestionsStep(questions=generated.questions)

        # No generator or generator returned 0 questions — run prediction directly
        await self._finalize_with_prediction(db, row, rule_based_pairs)
        await self._repo.set_pipeline_stage(db, row, PipelineStage.DONE)

        return self._build_pipeline_result(row)

    # ==================================================================
    # Internal: prediction and finalization
    # ==================================================================

    async def _finalize_with_prediction(
        self,
        db: AsyncSession,
        row: PrescreenSession,
        qa_pairs: list[QAPair],
    ) -> None:
        """Run prediction and merge results into the session's result JSONB.

        Rule-based departments/severity take precedence.  Prediction results
        are used as fallback if the rule-based engine didn't set them.
        Diagnoses from prediction are always stored.
        """
        if self._predictor is None:
            # No predictor — ensure result has an empty diagnoses list
            result = row.result or {}
            if "diagnoses" not in result:
                result["diagnoses"] = []
                row.result = result
                await db.flush()
            return

        prediction = await self._predictor.predict(qa_pairs)

        result = row.result or {}

        # Always store prediction diagnoses
        result["diagnoses"] = [
            {"disease_id": d.disease_id, "confidence": d.confidence}
            for d in prediction.diagnoses
        ]

        # Use prediction departments/severity as fallback only
        if not result.get("departments") and prediction.departments:
            result["departments"] = prediction.departments
        if not result.get("severity") and prediction.severity:
            result["severity"] = prediction.severity

        row.result = result
        await db.flush()

    def _build_pipeline_result(self, row: PrescreenSession) -> PipelineResult:
        """Construct a PipelineResult from the session's current state."""
        result = row.result or {}
        dept_ids = result.get("departments") or []
        sev_id = result.get("severity")
        raw_diagnoses = result.get("diagnoses") or []

        # Resolve department/severity IDs to full dicts
        departments = []
        for d in dept_ids:
            try:
                departments.append(self._store.resolve_department(d))
            except KeyError:
                logger.warning("Unknown department ID in result: %s", d)
                departments.append({"id": d})

        severity = None
        if sev_id:
            try:
                severity = self._store.resolve_severity(sev_id)
            except KeyError:
                logger.warning("Unknown severity ID in result: %s", sev_id)
                severity = {"id": sev_id}

        diagnoses = [
            DiagnosisResult(
                disease_id=d["disease_id"],
                confidence=d.get("confidence"),
            )
            for d in raw_diagnoses
        ]

        return PipelineResult(
            departments=departments,
            severity=severity,
            diagnoses=diagnoses,
            reason=result.get("reason") or row.termination_reason,
            terminated_early=(row.status == SessionStatus.TERMINATED),
        )

    # ==================================================================
    # Internal: Q&A pair reconstruction
    # ==================================================================

    def _build_qa_pairs(self, row: PrescreenSession) -> list[QAPair]:
        """Reconstruct the full rule-based Q&A history from session data.

        Builds pairs in phase order (0-5), skipping auto-eval question types
        and the ``__pending`` metadata key.  Each pair carries its source
        metadata for downstream consumers.
        """
        pairs: list[QAPair] = []

        # --- Phase 0: Demographics ---
        demographics = row.demographics or {}
        for field in self._store.demographics:
            value = demographics.get(field.key)
            if value is not None:
                pairs.append(QAPair(
                    question=field.field_name_th,
                    answer=value,
                    source="rule_based",
                    qid=field.qid,
                    question_type=field.type,
                    phase=0,
                ))

        # --- Phase 1: ER Critical ---
        for item in self._store.er_critical:
            resp = (row.responses or {}).get(item.qid)
            if resp is not None:
                # Extract value from response dict or use directly
                value = resp["value"] if isinstance(resp, dict) and "value" in resp else resp
                pairs.append(QAPair(
                    question=item.text,
                    answer=value,
                    source="rule_based",
                    qid=item.qid,
                    question_type="yes_no",
                    phase=1,
                ))

        # --- Phase 2: Symptom Selection ---
        if row.primary_symptom:
            pairs.append(QAPair(
                question="อาการหลัก",
                answer=row.primary_symptom,
                source="rule_based",
                qid="primary_symptom",
                question_type="single_select",
                phase=2,
            ))
        if row.secondary_symptoms:
            pairs.append(QAPair(
                question="อาการร่วม (ถ้ามี)",
                answer=row.secondary_symptoms,
                source="rule_based",
                qid="secondary_symptoms",
                question_type="multi_select",
                phase=2,
            ))

        # --- Phase 3: ER Checklist ---
        if row.primary_symptom:
            age = self._get_patient_age(row)
            pediatric = age is not None and age < PEDIATRIC_AGE_THRESHOLD
            symptoms = [row.primary_symptom]
            if row.secondary_symptoms:
                symptoms.extend(row.secondary_symptoms)

            for symptom in symptoms:
                items = self._store.get_er_checklist(symptom, pediatric=pediatric)
                for item in items:
                    resp = (row.responses or {}).get(item.qid)
                    if resp is not None:
                        value = (
                            resp["value"]
                            if isinstance(resp, dict) and "value" in resp
                            else resp
                        )
                        pairs.append(QAPair(
                            question=item.text,
                            answer=value,
                            source="rule_based",
                            qid=item.qid,
                            question_type="yes_no",
                            phase=3,
                        ))

        # --- Phases 4 & 5: OLDCARTS and OPD ---
        for phase_num, source in [(4, "oldcarts"), (5, "opd")]:
            if not row.primary_symptom:
                continue
            tree = (
                self._store.oldcarts if source == "oldcarts"
                else self._store.opd
            )
            questions_dict = tree.get(row.primary_symptom, {})
            for qid, question in questions_dict.items():
                # Skip auto-eval question types — they're invisible to the user
                if question.question_type in AUTO_EVAL_TYPES:
                    continue
                resp = (row.responses or {}).get(qid)
                if resp is not None:
                    value = (
                        resp["value"]
                        if isinstance(resp, dict) and "value" in resp
                        else resp
                    )
                    pairs.append(QAPair(
                        question=question.question,
                        answer=value,
                        source="rule_based",
                        qid=qid,
                        question_type=question.question_type,
                        phase=phase_num,
                    ))

        return pairs

    # ==================================================================
    # Internal: helpers
    # ==================================================================

    async def _load_session(
        self, db: AsyncSession, user_id: str, session_id: str
    ) -> PrescreenSession:
        """Load a session row or raise ValueError if not found."""
        row = await self._repo.get_by_user_and_session(db, user_id, session_id)
        if row is None:
            raise ValueError(
                f"Session not found: user_id={user_id}, session_id={session_id}"
            )
        return row

    @staticmethod
    def _get_patient_age(row: PrescreenSession) -> int | None:
        """Extract patient age from demographics. Returns None if unavailable."""
        demographics = row.demographics or {}

        if "age" in demographics:
            try:
                return int(demographics["age"])
            except (TypeError, ValueError):
                pass

        dob_str = demographics.get("date_of_birth")
        if dob_str:
            try:
                from datetime import date
                dob = date.fromisoformat(str(dob_str))
                today = date.today()
                age = today.year - dob.year
                if (today.month, today.day) < (dob.month, dob.day):
                    age -= 1
                return age
            except (ValueError, TypeError):
                pass

        return None
