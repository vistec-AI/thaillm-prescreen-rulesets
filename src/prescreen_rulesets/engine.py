"""PrescreenEngine — the main orchestrator for the 6-phase prescreening flow.

Stateless engine pattern: each call loads session state from the database,
computes the next step, persists changes, and returns the result.  No
in-memory state is kept between calls.

The engine accepts an ``AsyncSession`` from the caller so that the caller
(typically a FastAPI endpoint) controls transaction boundaries.

Phase overview:
    0  Demographics      — bulk: collect 8 demographic fields
    1  ER Critical Screen — bulk: 11 yes/no critical checks
    2  Symptom Selection  — bulk: NHSO symptom list (primary + secondary)
    3  ER Checklist       — bulk: age-appropriate checklist for selected symptoms
    4  OLDCARTS           — sequential: decision tree per symptom
    5  OPD                — sequential: decision tree per symptom
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from prescreen_db.models.enums import SessionStatus
from prescreen_db.models.session import PrescreenSession
from prescreen_db.repository import SessionRepository

from prescreen_rulesets.constants import (
    AUTO_EVAL_TYPES,
    DEFAULT_ER_DEPARTMENT,
    DEFAULT_ER_SEVERITY,
    PEDIATRIC_AGE_THRESHOLD,
    PHASE_NAMES,
    SEVERITY_ORDER,
)
from prescreen_rulesets.evaluator import ConditionalEvaluator
from prescreen_rulesets.models.action import GotoAction, OPDAction, TerminateAction
from prescreen_rulesets.models.question import (
    FreeTextQuestion,
    FreeTextWithFieldQuestion,
    ImageMultiSelectQuestion,
    ImageSelectQuestion,
    MultiSelectQuestion,
    NumberRangeQuestion,
    Question,
    SingleSelectQuestion,
)
from prescreen_rulesets.models.session import (
    QuestionPayload,
    QuestionsStep,
    SessionInfo,
    StepResult,
    TerminationStep,
)
from prescreen_rulesets.ruleset import RulesetStore

logger = logging.getLogger(__name__)

# Key used in the responses JSONB to store the pending-qid queue for
# sequential phases (4 OLDCARTS, 5 OPD).
_PENDING_KEY = "__pending"


class PrescreenEngine:
    """Orchestrates the prescreening flow across 6 phases.

    Args:
        store: a loaded :class:`RulesetStore` instance
    """

    def __init__(self, store: RulesetStore) -> None:
        self._store = store
        self._repo = SessionRepository()
        self._evaluator = ConditionalEvaluator()

    # ==================================================================
    # Session lifecycle
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

        The session starts at phase 0 (Demographics).  The caller must
        ``await db.commit()`` to persist.
        """
        row = await self._repo.create_session(
            db, user_id=user_id, session_id=session_id, ruleset_version=ruleset_version,
        )
        return self._to_session_info(row)

    async def get_session(
        self, db: AsyncSession, *, user_id: str, session_id: str
    ) -> SessionInfo | None:
        """Fetch session info by (user_id, session_id).  Returns None if not found."""
        row = await self._repo.get_by_user_and_session(db, user_id, session_id)
        if row is None:
            return None
        return self._to_session_info(row)

    async def list_sessions(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[SessionInfo]:
        """List sessions for a user, most recent first."""
        rows = await self._repo.list_by_user(db, user_id, limit=limit, offset=offset)
        return [self._to_session_info(r) for r in rows]

    # ==================================================================
    # Step API
    # ==================================================================

    async def get_current_step(
        self, db: AsyncSession, *, user_id: str, session_id: str
    ) -> StepResult:
        """Return the current step (questions to show or termination result).

        Does not modify session state — this is a read-only operation.
        """
        row = await self._load_session(db, user_id, session_id)
        return self._compute_step(row)

    async def submit_answer(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: str,
        qid: str,
        value: Any,
    ) -> StepResult:
        """Submit an answer for the current step and advance the session.

        For bulk phases (0-3), ``qid`` is a phase marker (e.g. "demographics",
        "er_critical", "symptoms", "er_checklist") and ``value`` is the
        full batch payload.

        For sequential phases (4-5), ``qid`` is the specific question ID
        and ``value`` is the user's answer.

        Returns the next step after processing.
        """
        row = await self._load_session(db, user_id, session_id)
        phase = row.current_phase

        if phase == 0:
            return await self._submit_demographics(db, row, value)
        elif phase == 1:
            return await self._submit_er_critical(db, row, value)
        elif phase == 2:
            return await self._submit_symptoms(db, row, value)
        elif phase == 3:
            return await self._submit_er_checklist(db, row, value)
        elif phase in (4, 5):
            return await self._submit_sequential(db, row, qid, value)
        else:
            raise ValueError(f"Invalid phase: {phase}")

    # ==================================================================
    # Internal: compute current step (read-only)
    # ==================================================================

    def _compute_step(self, row: PrescreenSession) -> StepResult:
        """Determine what step to show based on current session state."""
        # If session is already terminal, return the termination result
        if row.status in (SessionStatus.COMPLETED, SessionStatus.TERMINATED):
            return self._build_termination_step(row)

        phase = row.current_phase

        if phase == 0:
            return self._step_demographics()
        elif phase == 1:
            return self._step_er_critical()
        elif phase == 2:
            return self._step_symptom_selection()
        elif phase == 3:
            return self._step_er_checklist(row)
        elif phase in (4, 5):
            return self._step_sequential(row)
        else:
            raise ValueError(f"Invalid phase: {phase}")

    # --- Phase 0: Demographics ---

    def _step_demographics(self) -> QuestionsStep:
        """Build the demographics step — present all demographic fields as questions."""
        questions = []
        for field in self._store.demographics:
            payload = QuestionPayload(
                qid=field.qid,
                question=field.field_name_th,
                question_type=field.type,
                metadata={
                    "key": field.key,
                    "field_name": field.field_name,
                    "optional": field.optional,
                },
            )
            # Attach values for enum/from_yaml types
            if field.values is not None:
                if isinstance(field.values, list):
                    payload.options = [{"id": v, "label": v} for v in field.values]
                else:
                    # from_yaml: the values field is a filename reference
                    payload.metadata["values_source"] = field.values
            questions.append(payload)

        return QuestionsStep(
            phase=0,
            phase_name=PHASE_NAMES[0],
            questions=questions,
        )

    # --- Phase 1: ER Critical Screen ---

    def _step_er_critical(self) -> QuestionsStep:
        """Build the ER critical step — present all critical yes/no checks."""
        questions = [
            QuestionPayload(
                qid=item.qid,
                question=item.text,
                question_type="yes_no",
            )
            for item in self._store.er_critical
        ]
        return QuestionsStep(
            phase=1,
            phase_name=PHASE_NAMES[1],
            questions=questions,
        )

    # --- Phase 2: Symptom Selection ---

    def _step_symptom_selection(self) -> QuestionsStep:
        """Build the symptom selection step — present NHSO symptom list."""
        symptom_options = [
            {"id": sym.name, "label": sym.name_th}
            for sym in self._store.nhso_symptoms.values()
        ]
        questions = [
            QuestionPayload(
                qid="primary_symptom",
                question="อาการหลัก",
                question_type="single_select",
                options=symptom_options,
            ),
            QuestionPayload(
                qid="secondary_symptoms",
                question="อาการร่วม (ถ้ามี)",
                question_type="multi_select",
                options=symptom_options,
                metadata={"optional": True},
            ),
        ]
        return QuestionsStep(
            phase=2,
            phase_name=PHASE_NAMES[2],
            questions=questions,
        )

    # --- Phase 3: ER Checklist ---

    def _step_er_checklist(self, row: PrescreenSession) -> QuestionsStep:
        """Build the ER checklist step — age-appropriate items for selected symptoms."""
        age = self._get_patient_age(row)
        pediatric = age is not None and age < PEDIATRIC_AGE_THRESHOLD

        # Collect checklist items for primary + secondary symptoms
        symptoms = self._get_selected_symptoms(row)
        questions: list[QuestionPayload] = []

        for symptom in symptoms:
            items = self._store.get_er_checklist(symptom, pediatric=pediatric)
            for item in items:
                questions.append(QuestionPayload(
                    qid=item.qid,
                    question=item.text,
                    question_type="yes_no",
                    metadata={"symptom": symptom},
                ))

        return QuestionsStep(
            phase=3,
            phase_name=PHASE_NAMES[3],
            questions=questions,
        )

    # --- Phases 4/5: Sequential (OLDCARTS / OPD) ---

    def _step_sequential(self, row: PrescreenSession) -> StepResult:
        """Resolve the next user-facing question(s) for sequential phases.

        Uses the ``__pending`` queue in responses to track which qids
        still need to be presented.  Auto-evaluates filter/conditional
        questions transparently until a user-facing question is found.
        """
        phase = row.current_phase
        source = "oldcarts" if phase == 4 else "opd"
        symptom = row.primary_symptom

        # Get or initialize the pending queue
        pending = list(row.responses.get(_PENDING_KEY, []))

        # If no pending items, this phase just started — seed with first qid
        if not pending:
            try:
                first_qid = self._store.get_first_qid(source, symptom)
            except KeyError:
                # Symptom has no questions in this source — advance phase
                if phase == 4:
                    # Try to move to OPD
                    return self._build_advance_step(row, 5)
                else:
                    # Phase 5 done — build completion
                    return self._build_completion_step(row)
            pending = [first_qid]

        # Resolve: skip auto-eval questions, return first user-facing question
        return self._resolve_next(row, source, symptom, pending)

    def _resolve_next(
        self,
        row: PrescreenSession,
        source: str,
        symptom: str,
        pending: list[str],
    ) -> StepResult:
        """Pop qids from pending, auto-evaluate filters, return first user-facing question.

        If auto-eval produces a goto → add targets to pending and continue.
        If auto-eval produces opd → advance to phase 5.
        If auto-eval produces terminate → terminate the session.
        If we run out of pending → advance to next phase or complete.
        """
        answers = self._extract_answers(row)
        demographics = row.demographics

        while pending:
            qid = pending.pop(0)

            # Skip already-answered questions (de-duplication)
            if qid in answers:
                continue

            try:
                question = self._store.get_question(source, symptom, qid)
            except KeyError:
                logger.warning("qid %s not found in %s/%s, skipping", qid, source, symptom)
                continue

            # Check if this is an auto-eval type
            if question.question_type in AUTO_EVAL_TYPES:
                action = self._evaluator.evaluate(question, answers, demographics)
                if action is None:
                    logger.warning("Auto-eval returned None for %s, skipping", qid)
                    continue

                # Process the auto-eval action
                result = self._process_action(row, source, symptom, action, pending)
                if result is not None:
                    return result
                # If _process_action returned None, it was a goto that added
                # targets to pending — continue the loop
                continue

            # User-facing question — return it
            payload = self._question_to_payload(question)
            return QuestionsStep(
                phase=row.current_phase,
                phase_name=PHASE_NAMES[row.current_phase],
                questions=[payload],
            )

        # Pending queue exhausted — advance to next phase
        phase = row.current_phase
        if phase == 4:
            return self._build_advance_step(row, 5)
        else:
            return self._build_completion_step(row)

    # ==================================================================
    # Internal: submit handlers
    # ==================================================================

    async def _submit_demographics(
        self, db: AsyncSession, row: PrescreenSession, value: dict[str, Any]
    ) -> StepResult:
        """Process phase 0 demographics submission."""
        await self._repo.save_demographics(db, row, value)
        await self._repo.advance_phase(db, row, 1)
        return self._compute_step(row)

    async def _submit_er_critical(
        self, db: AsyncSession, row: PrescreenSession, value: dict[str, Any]
    ) -> StepResult:
        """Process phase 1 ER critical screen submission.

        ``value`` is a dict of {qid: bool} — True means the patient said "yes"
        to that critical item.  If ANY item is positive, terminate immediately.
        """
        # Record all responses
        for qid, ans in value.items():
            await self._repo.record_response(db, row, qid, ans)

        # Check for any positive critical items
        positive_qids = [qid for qid, ans in value.items() if ans is True]
        if positive_qids:
            return await self._terminate(
                db, row,
                departments=[DEFAULT_ER_DEPARTMENT],
                severity=DEFAULT_ER_SEVERITY,
                reason=f"ER critical positive: {', '.join(positive_qids)}",
            )

        # All negative — advance to phase 2
        await self._repo.advance_phase(db, row, 2)
        return self._compute_step(row)

    async def _submit_symptoms(
        self, db: AsyncSession, row: PrescreenSession, value: dict[str, Any]
    ) -> StepResult:
        """Process phase 2 symptom selection submission.

        ``value`` is a dict with keys "primary_symptom" (str) and optionally
        "secondary_symptoms" (list[str]).
        """
        primary = value["primary_symptom"]
        secondary = value.get("secondary_symptoms")

        await self._repo.save_symptom_selection(
            db, row, primary_symptom=primary, secondary_symptoms=secondary,
        )
        await self._repo.advance_phase(db, row, 3)
        return self._compute_step(row)

    async def _submit_er_checklist(
        self, db: AsyncSession, row: PrescreenSession, value: dict[str, Any]
    ) -> StepResult:
        """Process phase 3 ER checklist submission.

        ``value`` is a dict of {qid: bool}.  If ANY item is positive,
        terminate with the first positive item's severity/department
        (priority by YAML order).
        """
        # Save the raw flags
        await self._repo.save_er_flags(db, row, value)

        # Record each response
        for qid, ans in value.items():
            await self._repo.record_response(db, row, qid, ans)

        # Find the first positive item (by checklist order)
        age = self._get_patient_age(row)
        pediatric = age is not None and age < PEDIATRIC_AGE_THRESHOLD
        symptoms = self._get_selected_symptoms(row)

        first_positive = self._find_first_positive_er_item(
            value, symptoms, pediatric=pediatric,
        )

        if first_positive is not None:
            item, _ = first_positive
            dept, sev = self._resolve_er_item_result(item, pediatric=pediatric)
            return await self._terminate(
                db, row,
                departments=[dept],
                severity=sev,
                reason=f"ER checklist positive: {item.qid}",
            )

        # All negative — advance to phase 4 (OLDCARTS)
        await self._repo.advance_phase(db, row, 4)
        return self._compute_step(row)

    async def _submit_sequential(
        self, db: AsyncSession, row: PrescreenSession, qid: str, value: Any
    ) -> StepResult:
        """Process a single answer in phases 4 (OLDCARTS) or 5 (OPD).

        Records the answer, determines the resulting action from the question
        definition, and either navigates to the next question or terminates.
        """
        phase = row.current_phase
        source = "oldcarts" if phase == 4 else "opd"
        symptom = row.primary_symptom

        # Record the answer
        await self._repo.record_response(db, row, qid, value)

        # Look up the question to determine the action
        question = self._store.get_question(source, symptom, qid)
        action = self._determine_action(question, value)

        if action is None:
            logger.warning("No action determined for %s=%r, using pending queue", qid, value)
            # Fall through to resolve_next with existing pending
            pending = list(row.responses.get(_PENDING_KEY, []))
            return self._resolve_and_persist(db, row, source, symptom, pending)

        # Process the action
        pending = list(row.responses.get(_PENDING_KEY, []))
        result = self._process_action(row, source, symptom, action, pending)

        if result is not None:
            # Terminal action (terminate or opd/phase advance)
            if isinstance(result, TerminationStep):
                # Persist the termination
                if result.type == "terminated":
                    dept_ids = [d["id"] for d in result.departments]
                    sev_id = result.severity["id"] if result.severity else None
                    return await self._terminate(
                        db, row,
                        departments=dept_ids,
                        severity=sev_id,
                        reason=result.reason,
                    )
                else:
                    return await self._complete(db, row, result)
            elif isinstance(result, QuestionsStep):
                # Phase advance — persist and return
                if result.phase != row.current_phase:
                    await self._repo.advance_phase(db, row, result.phase)
                # Save pending state
                await self._save_pending(db, row, pending)
                return result
            return result

        # Goto action was processed — pending was mutated, save and resolve
        return await self._resolve_and_persist(db, row, source, symptom, pending)

    # ==================================================================
    # Internal: action processing
    # ==================================================================

    def _process_action(
        self,
        row: PrescreenSession,
        source: str,
        symptom: str,
        action: Any,
        pending: list[str],
    ) -> StepResult | None:
        """Process an action and optionally return a terminal StepResult.

        For ``goto``: adds target qids to pending, returns None (caller continues).
        For ``opd``: returns a step that advances to phase 5.
        For ``terminate``: returns a TerminationStep.
        """
        if isinstance(action, GotoAction):
            # Add goto targets to front of pending (they should be processed next),
            # but skip any already-answered qids
            answers = self._extract_answers(row)
            new_qids = [q for q in action.qid if q not in answers and q not in pending]
            pending[0:0] = new_qids
            return None

        if isinstance(action, OPDAction):
            # Transition from OLDCARTS (phase 4) to OPD (phase 5)
            return self._build_advance_step(row, 5)

        if isinstance(action, TerminateAction):
            dept_ids = action.department or []
            sev_ids = action.severity
            severity = sev_ids[0] if sev_ids else None
            return TerminationStep(
                type="terminated" if row.current_phase < 5 else "completed",
                phase=row.current_phase,
                departments=[self._store.resolve_department(d) for d in dept_ids],
                severity=self._store.resolve_severity(severity) if severity else None,
                reason=action.reason,
            )

        logger.warning("Unknown action type: %s", type(action))
        return None

    def _determine_action(self, question: Question, value: Any) -> Any:
        """Determine which action to execute based on the question type and user answer.

        For single_select: find the option matching the selected ID and return its action.
        For multi_select: return the question's ``next`` action.
        For free_text/number_range: return the ``on_submit`` action.
        For image variants: same logic as their non-image counterparts.
        """
        if isinstance(question, (SingleSelectQuestion, ImageSelectQuestion)):
            # value is the selected option ID
            for opt in question.options:
                if opt.id == value:
                    return opt.action
            logger.warning("No option matched value=%r for %s", value, question.qid)
            return None

        if isinstance(question, (MultiSelectQuestion, ImageMultiSelectQuestion)):
            return question.next

        if isinstance(question, (FreeTextQuestion, FreeTextWithFieldQuestion, NumberRangeQuestion)):
            return question.on_submit

        # age_filter / gender_filter — these are auto-evaluated and shouldn't
        # reach here, but handle them defensively
        if hasattr(question, "options") and hasattr(question.options[0], "action"):
            for opt in question.options:
                if opt.id == value:
                    return opt.action

        logger.warning("Cannot determine action for question type: %s", question.question_type)
        return None

    # ==================================================================
    # Internal: helpers
    # ==================================================================

    async def _load_session(
        self, db: AsyncSession, user_id: str, session_id: str
    ) -> PrescreenSession:
        """Load a session row or raise ValueError if not found."""
        row = await self._repo.get_by_user_and_session(db, user_id, session_id)
        if row is None:
            raise ValueError(f"Session not found: user_id={user_id}, session_id={session_id}")
        return row

    async def _terminate(
        self,
        db: AsyncSession,
        row: PrescreenSession,
        *,
        departments: list[str],
        severity: str | None,
        reason: str | None,
    ) -> TerminationStep:
        """Terminate the session and return a TerminationStep."""
        await self._repo.terminate_session(
            db, row, phase=row.current_phase, reason=reason or "",
        )
        # Also save the result so it's queryable
        result_payload = {
            "departments": departments,
            "severity": severity,
            "reason": reason,
        }
        row.result = result_payload
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()

        return TerminationStep(
            type="terminated",
            phase=row.current_phase,
            departments=[self._store.resolve_department(d) for d in departments],
            severity=self._store.resolve_severity(severity) if severity else None,
            reason=reason,
        )

    async def _complete(
        self,
        db: AsyncSession,
        row: PrescreenSession,
        step: TerminationStep,
    ) -> TerminationStep:
        """Complete the session normally (all phases finished)."""
        result_payload = {
            "departments": [d["id"] for d in step.departments],
            "severity": step.severity.get("id") if step.severity else None,
            "reason": step.reason,
        }
        await self._repo.complete_session(db, row, result_payload)
        return step

    async def _save_pending(
        self, db: AsyncSession, row: PrescreenSession, pending: list[str]
    ) -> None:
        """Persist the pending queue to the responses JSONB."""
        updated = {**row.responses, _PENDING_KEY: pending}
        row.responses = updated
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()

    async def _resolve_and_persist(
        self,
        db: AsyncSession,
        row: PrescreenSession,
        source: str,
        symptom: str,
        pending: list[str],
    ) -> StepResult:
        """Resolve the next step and persist pending queue changes."""
        step = self._resolve_next(row, source, symptom, pending)

        # If the step is a phase advance, persist it
        if isinstance(step, QuestionsStep) and step.phase != row.current_phase:
            await self._repo.advance_phase(db, row, step.phase)

        # If it's a termination, persist it
        if isinstance(step, TerminationStep):
            if step.type == "terminated":
                dept_ids = [d["id"] for d in step.departments]
                sev_id = step.severity["id"] if step.severity else None
                return await self._terminate(
                    db, row,
                    departments=dept_ids,
                    severity=sev_id,
                    reason=step.reason,
                )
            else:
                return await self._complete(db, row, step)

        # Save pending state
        await self._save_pending(db, row, pending)
        return step

    def _build_termination_step(self, row: PrescreenSession) -> TerminationStep:
        """Build a TerminationStep from an already-terminal session row."""
        result = row.result or {}
        dept_ids = result.get("departments", [])
        sev_id = result.get("severity")

        return TerminationStep(
            type="terminated" if row.status == SessionStatus.TERMINATED else "completed",
            phase=row.terminated_at_phase if row.terminated_at_phase is not None else row.current_phase,
            departments=[self._store.resolve_department(d) for d in dept_ids],
            severity=self._store.resolve_severity(sev_id) if sev_id else None,
            reason=result.get("reason") or row.termination_reason,
        )

    def _build_advance_step(self, row: PrescreenSession, next_phase: int) -> QuestionsStep:
        """Build a step for the next phase (used when current phase is exhausted)."""
        # Temporarily adjust phase to compute the next step
        original_phase = row.current_phase
        row.current_phase = next_phase
        # Clear pending queue for the new phase
        if _PENDING_KEY in row.responses:
            updated = {k: v for k, v in row.responses.items() if k != _PENDING_KEY}
            row.responses = updated
        step = self._compute_step(row)
        # Restore if needed (the DB write happens in the caller)
        if not isinstance(step, QuestionsStep):
            row.current_phase = original_phase
        return step

    def _build_completion_step(self, row: PrescreenSession) -> TerminationStep:
        """Build a completion step when all phases are finished.

        This happens when the OPD tree terminates with a terminate action,
        or when phase 5 pending queue is exhausted.
        """
        # If we get here, the OPD tree should have terminated with a result.
        # Build a default completion with no specific department.
        return TerminationStep(
            type="completed",
            phase=5,
            departments=[],
            severity=None,
            reason="All phases completed without explicit termination",
        )

    def _get_patient_age(self, row: PrescreenSession) -> int | None:
        """Extract patient age from demographics.

        Returns None if date_of_birth or age is not available.
        """
        demographics = row.demographics or {}

        # Direct age field (if stored)
        if "age" in demographics:
            try:
                return int(demographics["age"])
            except (TypeError, ValueError):
                pass

        # Compute from date_of_birth
        dob_str = demographics.get("date_of_birth")
        if dob_str:
            try:
                # Try ISO format first
                from datetime import date
                dob = date.fromisoformat(str(dob_str))
                today = date.today()
                age = today.year - dob.year
                # Adjust if birthday hasn't occurred yet this year
                if (today.month, today.day) < (dob.month, dob.day):
                    age -= 1
                return age
            except (ValueError, TypeError):
                pass

        return None

    def _get_selected_symptoms(self, row: PrescreenSession) -> list[str]:
        """Return list of all selected symptoms (primary + secondary)."""
        symptoms = []
        if row.primary_symptom:
            symptoms.append(row.primary_symptom)
        if row.secondary_symptoms:
            symptoms.extend(row.secondary_symptoms)
        return symptoms

    def _find_first_positive_er_item(
        self,
        flags: dict[str, Any],
        symptoms: list[str],
        *,
        pediatric: bool,
    ) -> tuple[Any, str] | None:
        """Find the first positive ER checklist item by YAML order.

        Returns (ERChecklistItem, symptom_name) or None if all negative.
        Priority is determined by the order items appear in the YAML file
        across all selected symptoms.
        """
        for symptom in symptoms:
            items = self._store.get_er_checklist(symptom, pediatric=pediatric)
            for item in items:
                if flags.get(item.qid) is True:
                    return (item, symptom)
        return None

    def _resolve_er_item_result(
        self, item: Any, *, pediatric: bool
    ) -> tuple[str, str]:
        """Extract department and severity from an ER checklist item.

        Returns (department_id, severity_id) with defaults applied.

        Adult items use ``min_severity``; pediatric items use ``severity``.
        Both default to sev003/dept002 if not explicitly set.
        """
        # Severity
        sev_field = item.severity if pediatric else item.min_severity
        if sev_field and isinstance(sev_field, dict) and "id" in sev_field:
            severity = sev_field["id"]
        else:
            severity = DEFAULT_ER_SEVERITY

        # Department
        if item.department and isinstance(item.department, list) and len(item.department) > 0:
            dept = item.department[0]
            if isinstance(dept, dict) and "id" in dept:
                department = dept["id"]
            else:
                department = DEFAULT_ER_DEPARTMENT
        else:
            department = DEFAULT_ER_DEPARTMENT

        return department, severity

    def _extract_answers(self, row: PrescreenSession) -> dict[str, Any]:
        """Extract flat answers dict from session responses.

        The responses JSONB stores {qid: {value, answered_at}}.  This method
        returns {qid: value} for evaluator consumption.  Skips the __pending
        metadata key.
        """
        answers: dict[str, Any] = {}
        for qid, entry in row.responses.items():
            if qid.startswith("__"):
                continue
            if isinstance(entry, dict) and "value" in entry:
                answers[qid] = entry["value"]
            else:
                # Direct value (e.g. from auto-eval recording)
                answers[qid] = entry
        return answers

    def _question_to_payload(self, question: Question) -> QuestionPayload:
        """Convert a typed Question model to a flat QuestionPayload for the API."""
        payload = QuestionPayload(
            qid=question.qid,
            question=question.question,
            question_type=question.question_type,
        )

        # Attach type-specific fields
        if isinstance(question, (SingleSelectQuestion, ImageSelectQuestion)):
            payload.options = [{"id": o.id, "label": o.label} for o in question.options]
        elif isinstance(question, (MultiSelectQuestion, ImageMultiSelectQuestion)):
            payload.options = [{"id": o.id, "label": o.label} for o in question.options]
        elif isinstance(question, NumberRangeQuestion):
            payload.constraints = {
                "min": question.min_value,
                "max": question.max_value,
                "step": question.step,
                "default": question.default_value,
            }
        elif isinstance(question, FreeTextWithFieldQuestion):
            payload.fields = [
                {"id": f.id, "label": f.label, "kind": f.kind}
                for f in question.fields
            ]

        # Attach image if present
        if isinstance(question, (ImageSelectQuestion, ImageMultiSelectQuestion)):
            payload.image = question.image

        return payload

    @staticmethod
    def _to_session_info(row: PrescreenSession) -> SessionInfo:
        """Convert an ORM row to a public SessionInfo."""
        return SessionInfo(
            user_id=row.user_id,
            session_id=row.session_id,
            status=row.status.value if isinstance(row.status, SessionStatus) else str(row.status),
            current_phase=row.current_phase,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
