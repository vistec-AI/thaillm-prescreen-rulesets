"""Database-level enumerations for prescreen sessions."""

import enum


class SessionStatus(str, enum.Enum):
    """Lifecycle states for a prescreen session.

    Transitions:
        created -> in_progress  (first question answered)
        in_progress -> completed (all phases done, result written)
        in_progress -> terminated (early exit, e.g. ER redirect)
    """

    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    TERMINATED = "terminated"
