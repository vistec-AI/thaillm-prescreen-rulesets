from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


class GotoAction(BaseModel):
    action: Literal["goto"] = "goto"
    qid: List[str]


class OPDAction(BaseModel):
    action: Literal["opd"] = "opd"


class TerminateAction(BaseModel):
    action: Literal["terminate"] = "terminate"
    reason: Optional[str] = None
    metadata: Dict[Literal["department"], List[str]]

    @property
    def department(self) -> Optional[List[str]]:
        return self.metadata["department"]

Action = Annotated[Union[GotoAction, OPDAction, TerminateAction], Field(discriminator="action")]
