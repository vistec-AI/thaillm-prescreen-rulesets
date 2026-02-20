"""Action models for prescreening question decision trees.

Actions define what happens after a user answers a question (or an auto-evaluated
question resolves):
  - GotoAction: navigate to one or more follow-up questions by qid
  - OPDAction: hand off to the OPD phase (phase 5)
  - TerminateAction: end the session with department routing and optional severity

The discriminated ``Action`` union uses the ``action`` field as its discriminator
so Pydantic can deserialise YAML dicts directly into the correct type.
"""

from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class GotoAction(BaseModel):
    """Navigate to one or more follow-up questions by qid."""

    action: Literal["goto"] = "goto"
    qid: List[str]


class OPDAction(BaseModel):
    """Hand off to the OPD phase (phase 5)."""

    action: Literal["opd"] = "opd"


class DepartmentRef(BaseModel):
    """Reference to a department by its ID (e.g. dept001)."""

    id: str


class SeverityRef(BaseModel):
    """Reference to a severity level by its ID (e.g. sev001)."""

    id: str


class TerminateMetadata(BaseModel):
    """Metadata for a terminate action: department routing and optional severity override.

    - department: list of {id} refs (can be empty for self-care / observation)
    - severity: optional list of {id} refs for severity override
    """

    department: List[DepartmentRef] = []
    severity: Optional[List[SeverityRef]] = None


class TerminateAction(BaseModel):
    """End the session with department routing and optional severity."""

    action: Literal["terminate"] = "terminate"
    reason: Optional[str] = None
    metadata: TerminateMetadata

    @property
    def department(self) -> List[str]:
        """Flat list of department IDs (e.g. ['dept002'])."""
        return [d.id for d in self.metadata.department]

    @property
    def severity(self) -> List[str]:
        """Flat list of severity IDs (e.g. ['sev001']), empty if not set."""
        if self.metadata.severity is None:
            return []
        return [s.id for s in self.metadata.severity]


# Discriminated union — Pydantic picks the right type based on the "action" field.
Action = Annotated[Union[GotoAction, OPDAction, TerminateAction], Field(discriminator="action")]
