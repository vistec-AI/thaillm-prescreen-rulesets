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
from datetime import date, datetime, timezone
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


def _demographic_answer_schema(field) -> dict:
    """Map a DemographicField.type to a JSON-Schema-like dict.

    Used to tell LLM players what format each demographic answer should have.
    """
    ftype = field.type
    if ftype == "datetime":
        return {"type": "string", "format": "date"}
    elif ftype == "enum":
        # enum fields always have a list of allowed string values
        values = field.values if isinstance(field.values, list) else []
        return {"type": "string", "enum": values}
    elif ftype == "float":
        return {"type": "number"}
    elif ftype == "from_yaml":
        # from_yaml fields may carry a list of values or just a file reference
        if isinstance(field.values, list):
            return {"type": "string", "enum": field.values}
        return {"type": "string"}
    else:
        # str and any unknown types default to string
        return {"type": "string"}


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
        qid: str | None = None,
        value: Any,
    ) -> StepResult:
        """Submit an answer for the current step and advance the session.

        For bulk phases (0-3), ``qid`` is a phase marker (e.g. "demographics",
        "er_critical", "symptoms", "er_checklist") and ``value`` is the
        full batch payload.  ``qid`` is ignored in these phases, so passing
        ``None`` (the default) is fine.

        For sequential phases (4-5), ``qid`` identifies which question is
        being answered.  If ``None``, the engine auto-derives it from the
        current step (i.e. ``_compute_step(row).questions[0].qid``), which
        is always the single question the engine last presented.

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
            # Auto-derive qid when the caller omits it — sequential phases
            # present exactly one question at a time, so the current step's
            # first question qid is always the right one.
            resolved_qid = qid if qid is not None else self._derive_current_qid(row)
            return await self._submit_sequential(db, row, resolved_qid, value)
        else:
            raise ValueError(f"Invalid phase: {phase}")

    # ==================================================================
    # Step-back API
    # ==================================================================

    async def step_back(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: str,
    ) -> StepResult:
        """Go back one step — automatically determines the previous step.

        Computes the "previous step" from the current session state and
        delegates to :meth:`back_edit`.  This is a convenience wrapper
        that frees integrators from needing to know the internal
        phase/qid of the previous question.

        Only valid when the session is ``created`` or ``in_progress``.

        Returns:
            The step at the previous position (same shape as back_edit).

        Raises:
            ValueError: if the session is terminal or already at the
                first step (phase 0 with no prior answers).
        """
        row = await self._load_session(db, user_id, session_id)

        # Validate session status — must be active
        if row.status not in (SessionStatus.CREATED, SessionStatus.IN_PROGRESS):
            raise ValueError(
                f"Cannot step back: session status is '{row.status.value}', "
                f"expected 'created' or 'in_progress'"
            )

        target_phase, target_qid = self._resolve_previous_step(row)

        return await self.back_edit(
            db,
            user_id=user_id,
            session_id=session_id,
            target_phase=target_phase,
            target_qid=target_qid,
        )

    def _resolve_previous_step(
        self, row: PrescreenSession
    ) -> tuple[int, str | None]:
        """Compute (target_phase, target_qid) for going back one step.

        Decision table:
          - Phase 0: error — already at first step
          - Phase 1: go to phase 0
          - Phase 2: go to phase 1
          - Phase 3: go to phase 2
          - Phase 4 with answered OLDCARTS questions: go to last answered OLDCARTS qid
          - Phase 4 with no answered OLDCARTS questions: go to phase 3
          - Phase 5 with answered OPD questions: go to last answered OPD qid
          - Phase 5 with no OPD answers but has OLDCARTS answers: go to last OLDCARTS qid
          - Phase 5 with no OPD or OLDCARTS answers: go to phase 3

        Returns:
            (target_phase, target_qid) — target_qid is None for bulk phases.

        Raises:
            ValueError: if already at the first step (phase 0).
        """
        phase = row.current_phase

        if phase == 0:
            raise ValueError("Cannot step back: already at the first step (phase 0)")

        # Bulk phases 1-3: simply go to the previous phase
        if phase in (1, 2, 3):
            return (phase - 1, None)

        symptom = row.primary_symptom

        if phase == 4:
            # Check for answered OLDCARTS questions
            if symptom:
                oldcarts_qids = set(self._store.oldcarts.get(symptom, {}).keys())
                last_qid = self._find_last_answered_qid(row, oldcarts_qids)
                if last_qid is not None:
                    return (4, last_qid)
            # No OLDCARTS answers yet — go back to phase 3
            return (3, None)

        if phase == 5:
            # First check for answered OPD questions
            if symptom:
                opd_qids = set(self._store.opd.get(symptom, {}).keys())
                last_opd_qid = self._find_last_answered_qid(row, opd_qids)
                if last_opd_qid is not None:
                    return (5, last_opd_qid)

                # No OPD answers — check for OLDCARTS answers
                oldcarts_qids = set(self._store.oldcarts.get(symptom, {}).keys())
                last_oldcarts_qid = self._find_last_answered_qid(row, oldcarts_qids)
                if last_oldcarts_qid is not None:
                    return (4, last_oldcarts_qid)

            # No OPD or OLDCARTS answers — go back to phase 3
            return (3, None)

        raise ValueError(f"Invalid phase: {phase}")

    def _find_last_answered_qid(
        self, row: PrescreenSession, tree_qids: set[str]
    ) -> str | None:
        """Find the most recently answered qid among ``tree_qids``.

        Looks at the ``answered_at`` timestamp in each response entry
        and returns the qid with the latest timestamp.  Returns ``None``
        if no qids from ``tree_qids`` have been answered.
        """
        latest_qid: str | None = None
        latest_time: str = ""

        for qid in tree_qids:
            entry = row.responses.get(qid)
            if entry is None:
                continue
            # Response entries are stored as {value, answered_at} dicts
            if isinstance(entry, dict) and "answered_at" in entry:
                answered_at = entry["answered_at"]
                if answered_at > latest_time:
                    latest_time = answered_at
                    latest_qid = qid

        return latest_qid

    # ==================================================================
    # Back-edit API
    # ==================================================================

    async def back_edit(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: str,
        target_phase: int,
        target_qid: str | None = None,
    ) -> StepResult:
        """Revert the session to a previous phase (or question within a phase).

        Allows integrators to jump back to any earlier step during the
        rule-based pipeline stage.  Clears responses and state from the
        target phase onward, then returns the restored step.

        For bulk phases (0-3), only ``target_phase`` is needed — the entire
        phase is re-presented.  For sequential phases (4-5), an optional
        ``target_qid`` allows jumping to a specific question within the phase.

        Args:
            target_phase: the phase to revert to (0-5)
            target_qid: for phases 4-5, jump to a specific question.
                Must be a qid that was previously answered in the session.

        Returns:
            The step at the reverted position (same shape as get_current_step).

        Raises:
            ValueError: if the session is terminal, target is invalid, or
                target_qid is not found in prior responses.
        """
        row = await self._load_session(db, user_id, session_id)

        # --- Validation ---
        if row.status not in (SessionStatus.CREATED, SessionStatus.IN_PROGRESS):
            raise ValueError(
                f"Cannot back-edit: session status is '{row.status.value}', "
                f"expected 'created' or 'in_progress'"
            )

        if target_phase < 0 or target_phase > 5:
            raise ValueError(
                f"target_phase must be 0-5, got {target_phase}"
            )

        # target_qid is only valid for sequential phases (4-5)
        if target_qid is not None and target_phase not in (4, 5):
            raise ValueError(
                f"target_qid is only valid for phases 4-5, "
                f"got target_phase={target_phase}"
            )

        # Must go to an earlier phase, OR same phase with target_qid for
        # intra-phase back-edit in sequential phases
        if target_phase > row.current_phase:
            raise ValueError(
                f"target_phase ({target_phase}) must be <= current_phase "
                f"({row.current_phase})"
            )
        if target_phase == row.current_phase and target_qid is None:
            raise ValueError(
                f"target_phase ({target_phase}) equals current_phase — "
                f"provide target_qid for intra-phase back-edit in phases 4-5"
            )

        # If target_qid is provided, verify it exists in prior responses
        if target_qid is not None:
            if target_qid not in row.responses or target_qid.startswith("__"):
                raise ValueError(
                    f"target_qid '{target_qid}' not found in session responses"
                )

        # --- Snapshot previous values for bulk phases (pre-population) ---
        # For bulk phases 0-3, capture the current values so the UI can
        # pre-fill the form with the patient's previous answers.
        previous_values: dict[str, Any] = {}
        if target_phase == 0:
            previous_values = dict(row.demographics or {})
        elif target_phase == 1:
            # Collect ER critical answers from responses
            for item in self._store.er_critical:
                resp = row.responses.get(item.qid)
                if resp is not None:
                    val = resp["value"] if isinstance(resp, dict) and "value" in resp else resp
                    previous_values[item.qid] = val
        elif target_phase == 2:
            if row.primary_symptom:
                previous_values["primary_symptom"] = row.primary_symptom
            if row.secondary_symptoms:
                previous_values["secondary_symptoms"] = row.secondary_symptoms
        elif target_phase == 3:
            previous_values = dict(row.er_flags or {})

        # --- Compute what to clear ---
        params = self._compute_back_edit_params(row, target_phase, target_qid)

        # --- Apply the revert ---
        await self._repo.revert_session_state(db, row, **params)

        # --- Compute and return the restored step ---
        step = self._compute_step(row)

        # Inject previous_value into question metadata for bulk phases so
        # UIs can pre-fill forms with the patient's earlier answers.
        if previous_values and isinstance(step, QuestionsStep):
            for q in step.questions:
                prev = previous_values.get(
                    q.metadata.get("key") if q.metadata and "key" in q.metadata else q.qid
                )
                if prev is not None:
                    if q.metadata is None:
                        q.metadata = {}
                    q.metadata["previous_value"] = prev

        return step

    def _compute_back_edit_params(
        self,
        row: PrescreenSession,
        target_phase: int,
        target_qid: str | None,
    ) -> dict:
        """Determine which data to clear when reverting to target_phase.

        Returns a dict of kwargs for ``repo.revert_session_state()``.

        Clearing strategy by target_phase:
          - Phase 0: clear everything (demographics, symptoms, er_flags, all responses)
          - Phase 1: keep demographics; clear symptoms, er_flags, all phase 1+ responses
          - Phase 2: keep demographics + phase 1 responses; clear symptoms, er_flags, phase 2+ responses
          - Phase 3: keep demographics + symptoms + phase 1-2 responses; clear er_flags, phase 3+ responses
          - Phase 4: keep all bulk data; clear phase 4+ responses and __pending
          - Phase 5: keep all bulk data + phase 4 responses; clear phase 5 responses and __pending

        For qid-level back-edit (phases 4-5), remove the target qid and
        all qids answered after it, then rebuild the __pending queue
        starting from the target qid.
        """
        # Collect qid sets by phase for removal
        er_critical_qids = {item.qid for item in self._store.er_critical}
        symptom = row.primary_symptom

        # Phase 3 ER checklist qids (need symptom + age info)
        er_checklist_qids: set[str] = set()
        if symptom:
            age = self._get_patient_age(row)
            pediatric = age is not None and age < PEDIATRIC_AGE_THRESHOLD
            symptoms = self._get_selected_symptoms(row)
            for sym in symptoms:
                items = self._store.get_er_checklist(sym, pediatric=pediatric)
                er_checklist_qids.update(item.qid for item in items)

        # Phase 4/5 qids from decision trees
        oldcarts_qids: set[str] = set()
        opd_qids: set[str] = set()
        if symptom:
            oldcarts_qids = set(self._store.oldcarts.get(symptom, {}).keys())
            opd_qids = set(self._store.opd.get(symptom, {}).keys())

        # Determine qids to remove and flags to clear
        qids_to_remove: set[str] = set()
        clear_demographics = False
        clear_symptoms = False
        clear_er_flags = False
        new_pending: list[str] | None = None

        if target_phase == 0:
            clear_demographics = True
            clear_symptoms = True
            clear_er_flags = True
            # Remove all response qids
            qids_to_remove = {
                k for k in row.responses if not k.startswith("__")
            }

        elif target_phase == 1:
            clear_symptoms = True
            clear_er_flags = True
            # Remove phase 1+ qids
            qids_to_remove = (
                er_critical_qids | er_checklist_qids | oldcarts_qids | opd_qids
            )

        elif target_phase == 2:
            clear_symptoms = True
            clear_er_flags = True
            # Remove phase 2+ qids (keep phase 1 ER critical responses)
            qids_to_remove = er_checklist_qids | oldcarts_qids | opd_qids

        elif target_phase == 3:
            clear_er_flags = True
            # Remove phase 3+ qids
            qids_to_remove = er_checklist_qids | oldcarts_qids | opd_qids

        elif target_phase == 4:
            # Remove phase 4+ qids
            qids_to_remove = oldcarts_qids | opd_qids

        elif target_phase == 5:
            # Remove phase 5 qids only
            qids_to_remove = opd_qids

        # --- Qid-level back-edit for phases 4-5 ---
        if target_qid is not None and target_phase in (4, 5):
            # Find all qids answered at or after the target qid (by timestamp)
            target_entry = row.responses.get(target_qid, {})
            target_time = (
                target_entry.get("answered_at", "")
                if isinstance(target_entry, dict)
                else ""
            )

            # Determine which tree we're working with
            tree_qids = oldcarts_qids if target_phase == 4 else opd_qids
            source = "oldcarts" if target_phase == 4 else "opd"

            # Collect qids answered at or after target_qid
            qids_to_remove = set()
            for qid in tree_qids:
                if qid == target_qid:
                    qids_to_remove.add(qid)
                    continue
                entry = row.responses.get(qid, {})
                if isinstance(entry, dict) and entry.get("answered_at", "") >= target_time:
                    qids_to_remove.add(qid)

            # Also remove OPD qids if we're going back to phase 4
            if target_phase == 4:
                qids_to_remove |= opd_qids

            # Rebuild the __pending queue starting from target_qid
            new_pending = [target_qid]

        # Only intersect with qids actually present in responses
        existing_qids = {k for k in row.responses if not k.startswith("__")}
        qids_to_remove &= existing_qids

        return {
            "target_phase": target_phase,
            "clear_demographics": clear_demographics,
            "clear_symptoms": clear_symptoms,
            "clear_er_flags": clear_er_flags,
            "response_qids_to_remove": qids_to_remove if qids_to_remove else None,
            "new_pending": new_pending,
        }

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
        # Track required keys for the submission_schema object
        required_keys: list[str] = []

        for field in self._store.demographics:
            payload = QuestionPayload(
                qid=field.qid,
                question=field.field_name_th,
                question_type=field.type,
                answer_schema=_demographic_answer_schema(field),
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

            if not field.optional:
                required_keys.append(field.key)

            questions.append(payload)

        # submission_schema: an object keyed by demographic field key
        properties = {
            f.key: _demographic_answer_schema(f)
            for f in self._store.demographics
        }
        submission_schema = {
            "type": "object",
            "properties": properties,
            "required": required_keys,
        }

        return QuestionsStep(
            phase=0,
            phase_name=PHASE_NAMES[0],
            questions=questions,
            submission_schema=submission_schema,
        )

    # --- Phase 1: ER Critical Screen ---

    def _step_er_critical(self) -> QuestionsStep:
        """Build the ER critical step — present all critical yes/no checks."""
        # Every ER critical question is a boolean yes/no
        boolean_schema = {"type": "boolean"}
        questions = [
            QuestionPayload(
                qid=item.qid,
                question=item.text,
                question_type="yes_no",
                answer_schema=boolean_schema,
            )
            for item in self._store.er_critical
        ]

        # submission_schema: object keyed by qid → boolean
        submission_schema = {
            "type": "object",
            "properties": {item.qid: boolean_schema for item in self._store.er_critical},
            "required": [item.qid for item in self._store.er_critical],
        }

        return QuestionsStep(
            phase=1,
            phase_name=PHASE_NAMES[1],
            questions=questions,
            submission_schema=submission_schema,
        )

    # --- Phase 2: Symptom Selection ---

    def _step_symptom_selection(self) -> QuestionsStep:
        """Build the symptom selection step — present NHSO symptom list."""
        symptom_options = [
            {"id": sym.name, "label": sym.name_th}
            for sym in self._store.nhso_symptoms.values()
        ]
        symptom_ids = [sym.name for sym in self._store.nhso_symptoms.values()]

        primary_schema = {"type": "string", "enum": symptom_ids}
        secondary_schema = {
            "type": "array",
            "items": {"type": "string", "enum": symptom_ids},
        }

        questions = [
            QuestionPayload(
                qid="primary_symptom",
                question="อาการหลัก",
                question_type="single_select",
                options=symptom_options,
                answer_schema=primary_schema,
            ),
            QuestionPayload(
                qid="secondary_symptoms",
                question="อาการร่วม (ถ้ามี)",
                question_type="multi_select",
                options=symptom_options,
                metadata={"optional": True},
                answer_schema=secondary_schema,
            ),
        ]

        # submission_schema: object with primary_symptom (required) and
        # secondary_symptoms (optional)
        submission_schema = {
            "type": "object",
            "properties": {
                "primary_symptom": primary_schema,
                "secondary_symptoms": secondary_schema,
            },
            "required": ["primary_symptom"],
        }

        return QuestionsStep(
            phase=2,
            phase_name=PHASE_NAMES[2],
            questions=questions,
            submission_schema=submission_schema,
        )

    # --- Phase 3: ER Checklist ---

    def _step_er_checklist(self, row: PrescreenSession) -> QuestionsStep:
        """Build the ER checklist step — age-appropriate items for selected symptoms."""
        age = self._get_patient_age(row)
        pediatric = age is not None and age < PEDIATRIC_AGE_THRESHOLD

        # Collect checklist items for primary + secondary symptoms
        symptoms = self._get_selected_symptoms(row)
        questions: list[QuestionPayload] = []
        boolean_schema = {"type": "boolean"}

        for symptom in symptoms:
            items = self._store.get_er_checklist(symptom, pediatric=pediatric)
            for item in items:
                questions.append(QuestionPayload(
                    qid=item.qid,
                    question=item.text,
                    question_type="yes_no",
                    answer_schema=boolean_schema,
                    metadata={"symptom": symptom},
                ))

        # submission_schema: object keyed by qid → boolean
        submission_schema = {
            "type": "object",
            "properties": {q.qid: boolean_schema for q in questions},
            "required": [q.qid for q in questions],
        }

        return QuestionsStep(
            phase=3,
            phase_name=PHASE_NAMES[3],
            questions=questions,
            submission_schema=submission_schema,
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
        demographics = dict(row.demographics or {})

        # Ensure computed age is available for age_filter evaluation.
        # Demographics may only contain date_of_birth (no explicit "age"
        # key), so we derive it here to avoid silent age_filter failures.
        if "age" not in demographics:
            age = self._get_patient_age(row)
            if age is not None:
                demographics["age"] = age

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

            # User-facing question — return it.  Sequential phases present
            # exactly one question, so submission_schema == answer_schema.
            payload = self._question_to_payload(question)
            return QuestionsStep(
                phase=row.current_phase,
                phase_name=PHASE_NAMES[row.current_phase],
                questions=[payload],
                submission_schema=payload.answer_schema,
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

    def _validate_demographics(self, value: Any) -> None:
        """Validate the phase 0 demographics payload.

        Checks that ``value`` is a dict with correct types for each
        demographic field.  Required fields must be present and non-None;
        optional fields are skipped when absent but validated when present.
        Extra keys (e.g. ``"age"``) are silently accepted for backward
        compatibility.

        Raises:
            ValueError: with a descriptive message if any check fails.
        """
        if not isinstance(value, dict):
            raise ValueError(
                "Demographics value must be a dict, "
                f"got {type(value).__name__}"
            )

        # Build a lookup of demographic field definitions keyed by field key
        field_by_key = {f.key: f for f in self._store.demographics}

        # Build a set of valid underlying disease names for from_yaml checks
        valid_ud_names = {ud.name for ud in self._store.underlying_diseases}

        for key, field in field_by_key.items():
            is_present = key in value and value[key] is not None

            # --- Required-field check ---
            if not field.optional and not is_present:
                raise ValueError(
                    f"Missing required demographic field: '{key}'"
                )

            # Skip absent optional fields
            if not is_present:
                continue

            val = value[key]
            ftype = field.type

            # --- datetime: must be ISO date string, not in the future ---
            if ftype == "datetime":
                if not isinstance(val, str):
                    raise ValueError(
                        f"Field '{key}' must be a date string (YYYY-MM-DD), "
                        f"got {type(val).__name__}"
                    )
                try:
                    parsed = date.fromisoformat(val)
                except ValueError:
                    raise ValueError(
                        f"Field '{key}' has invalid date format: '{val}'. "
                        "Expected YYYY-MM-DD"
                    )
                if parsed > date.today():
                    raise ValueError(
                        f"Field '{key}' must not be in the future: '{val}'"
                    )

            # --- enum: must be one of the allowed values ---
            elif ftype == "enum":
                allowed = field.values if isinstance(field.values, list) else []
                if not isinstance(val, str):
                    raise ValueError(
                        f"Field '{key}' must be a string, "
                        f"got {type(val).__name__}"
                    )
                if val not in allowed:
                    raise ValueError(
                        f"Field '{key}' must be one of {allowed}, "
                        f"got '{val}'"
                    )

            # --- float: must be numeric (int or float, not bool), positive ---
            elif ftype == "float":
                # bool is a subclass of int in Python, so reject it explicitly
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    raise ValueError(
                        f"Field '{key}' must be a number, "
                        f"got {type(val).__name__}"
                    )
                if val <= 0:
                    raise ValueError(
                        f"Field '{key}' must be positive, got {val}"
                    )

            # --- from_yaml: must be a list of valid names ---
            elif ftype == "from_yaml":
                if not isinstance(val, list):
                    raise ValueError(
                        f"Field '{key}' must be a list, "
                        f"got {type(val).__name__}"
                    )
                for item in val:
                    if not isinstance(item, str):
                        raise ValueError(
                            f"Field '{key}' items must be strings, "
                            f"got {type(item).__name__}"
                        )
                    if item not in valid_ud_names:
                        raise ValueError(
                            f"Field '{key}' contains unknown value: '{item}'"
                        )

            # --- str: must be a string if present ---
            elif ftype == "str":
                if not isinstance(val, str):
                    raise ValueError(
                        f"Field '{key}' must be a string, "
                        f"got {type(val).__name__}"
                    )

    async def _submit_demographics(
        self, db: AsyncSession, row: PrescreenSession, value: dict[str, Any]
    ) -> StepResult:
        """Process phase 0 demographics submission."""
        self._validate_demographics(value)
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
            # Use custom reasons from YAML if available, else fall back to
            # auto-generated format with qid identifiers.
            qid_to_item = {item.qid: item for item in self._store.er_critical}
            custom_reasons = [
                qid_to_item[qid].reason
                for qid in positive_qids
                if qid in qid_to_item and qid_to_item[qid].reason
            ]
            reason = (
                "; ".join(custom_reasons) if custom_reasons
                else f"ER critical positive: {', '.join(positive_qids)} (default response)"
            )
            return await self._terminate(
                db, row,
                departments=[DEFAULT_ER_DEPARTMENT],
                severity=DEFAULT_ER_SEVERITY,
                reason=reason,
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
            # Use the item's custom reason if provided, else fall back to
            # auto-generated format with qid identifier.
            reason = item.reason or f"ER checklist positive: {item.qid} (default response)"
            return await self._terminate(
                db, row,
                departments=[dept],
                severity=sev,
                reason=reason,
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
            return await self._resolve_and_persist(db, row, source, symptom, pending)

        # Process the action
        pending = list(row.responses.get(_PENDING_KEY, []))
        result = self._process_action(row, source, symptom, action, pending)

        if result is not None:
            # Terminal action (terminate or opd/phase advance)
            if isinstance(result, TerminationStep):
                # When the termination comes from a phase advance (e.g. OPD
                # auto-eval chain terminated without user-facing questions),
                # advance the session phase so the record correctly reflects
                # that the next phase was processed.
                if result.phase != row.current_phase:
                    await self._repo.advance_phase(db, row, result.phase)
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
                # Phase advance (e.g. OPDAction from OLDCARTS → OPD).
                if result.phase != phase:
                    await self._repo.advance_phase(db, row, result.phase)
                    # Re-derive the pending for the new phase by starting
                    # from its first question.  _resolve_and_persist runs
                    # the full auto-eval chain and saves the complete
                    # pending queue (including remaining goto targets that
                    # _build_advance_step computed locally but couldn't
                    # persist).
                    new_source = "oldcarts" if row.current_phase == 4 else "opd"
                    first_qid = self._store.get_first_qid(
                        new_source, row.primary_symptom,
                    )
                    return await self._resolve_and_persist(
                        db, row, new_source, row.primary_symptom, [first_qid],
                    )
                # Same phase — save pending state as-is
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

    def _derive_current_qid(self, row: PrescreenSession) -> str:
        """Derive the current question ID from the session's step.

        Used when callers omit ``qid`` during sequential phases (4-5).
        The engine always presents exactly one question at a time in these
        phases, so ``_compute_step(row).questions[0].qid`` is deterministic.

        Raises:
            ValueError: if the session is terminal or the step has no questions
        """
        step = self._compute_step(row)
        if not isinstance(step, QuestionsStep):
            raise ValueError(
                "Cannot derive qid: session is terminal "
                f"(status={row.status}, phase={row.current_phase})"
            )
        if not step.questions:
            raise ValueError(
                "Cannot derive qid: current step has no questions "
                f"(phase={row.current_phase})"
            )
        return step.questions[0].qid

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
        """Resolve the next step and persist pending queue changes.

        When the resolved step is a user-facing ``QuestionsStep``, the
        presented question's qid is kept at the front of the saved pending
        queue.  This is essential so that ``_derive_current_qid`` (which
        re-computes the step from the persisted pending) derives the
        *same* qid that was just presented — not the *next* one.
        """
        step = self._resolve_next(row, source, symptom, pending)

        # If the step is a phase advance, persist it
        if isinstance(step, QuestionsStep) and step.phase != row.current_phase:
            await self._repo.advance_phase(db, row, step.phase)

        # If it's a termination, persist it
        if isinstance(step, TerminationStep):
            # When the termination comes from a phase advance (e.g. pending
            # queue exhausted in OLDCARTS → OPD auto-eval chain terminates),
            # advance the session phase so the record correctly reflects
            # that the next phase was processed.
            if step.phase != row.current_phase:
                await self._repo.advance_phase(db, row, step.phase)
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

        # Keep the currently-presented question in the pending queue so
        # that _derive_current_qid can re-derive the same step.  The qid
        # will be skipped on the *next* submit because it will then exist
        # in the answers dict.
        if isinstance(step, QuestionsStep) and step.questions:
            current_qid = step.questions[0].qid
            pending.insert(0, current_qid)

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

        # Attach type-specific fields and answer_schema
        if isinstance(question, (SingleSelectQuestion, ImageSelectQuestion)):
            payload.options = [{"id": o.id, "label": o.label} for o in question.options]
            option_ids = [o.id for o in question.options]
            payload.answer_schema = {"type": "string", "enum": option_ids}

        elif isinstance(question, (MultiSelectQuestion, ImageMultiSelectQuestion)):
            payload.options = [{"id": o.id, "label": o.label} for o in question.options]
            option_ids = [o.id for o in question.options]
            payload.answer_schema = {
                "type": "array",
                "items": {"type": "string", "enum": option_ids},
            }

        elif isinstance(question, NumberRangeQuestion):
            payload.constraints = {
                "min": question.min_value,
                "max": question.max_value,
                "step": question.step,
                "default": question.default_value,
            }
            payload.answer_schema = {
                "type": "number",
                "minimum": question.min_value,
                "maximum": question.max_value,
            }

        elif isinstance(question, FreeTextWithFieldQuestion):
            payload.fields = [
                {"id": f.id, "label": f.label, "kind": f.kind}
                for f in question.fields
            ]
            # Build an object schema where each sub-field is a string property
            properties = {f.id: {"type": "string"} for f in question.fields}
            required = [f.id for f in question.fields]
            payload.answer_schema = {
                "type": "object",
                "properties": properties,
                "required": required,
            }

        elif isinstance(question, FreeTextQuestion):
            payload.answer_schema = {"type": "string"}

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
