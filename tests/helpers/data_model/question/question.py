from __future__ import annotations
from typing import Any, List, Optional, Union, Annotated, Literal
from pydantic import BaseModel, Field, model_validator

from helpers.data_model.question.action import Action

# base question typing
class BaseQuestion(BaseModel):
    qid: str
    question: str

    @property
    def is_oldcarts(self) -> bool:
        return "_opd_" not in self.qid
    
    @property
    def oldcarts_state(self) -> Optional[Literal["o", "l", "d", "c", "a", "r", "t", "s", "as"]]:
        if not self.is_oldcarts:
            return None
        return self.qid.split("_")[1]

class Option(BaseModel):
    id: str
    label: str


class ActionOption(Option):
    action: Action


class TextField(BaseModel):
    id: str
    label: str
    kind: Literal["text"]


# question variants
class FreeTextQuestion(BaseQuestion):
    question_type: Literal["free_text"] = "free_text"
    on_submit: Action

class FreeTextWithFieldQuestion(BaseQuestion):
    question_type: Literal["free_text_with_fields"] = "free_text_with_fields"
    fields: List[TextField]
    on_submit: Action

class NumberRangeQuestion(BaseQuestion):
    question_type: Literal["number_range"] = "number_range"
    min_value: float
    max_value: float
    step: float = 1.0
    on_submit: Action

    @model_validator(mode="after")
    def _chk(self):
        if self.min_value >= self.max_value:
            raise ValueError("min_value must be < max_value")
        return self

class SingleSelectQuestion(BaseQuestion):
    question_type: Literal["single_select"] = "single_select"
    options: List[ActionOption]

class MultiSelectQuestion(BaseQuestion):
    question_type: Literal["multi_select"] = "multi_select"
    options: List[Option]          # options have NO per-option actions
    next: Action

class ImageHotspot(Option):
    image: Optional[str] = None

class ImageSelectQuestion(BaseQuestion):
    question_type: Literal["image_single_select"] = "image_single_select"
    image: str
    options: List[ImageHotspot]

class GenderQuestion(BaseQuestion):
    question_type: Literal["gender_filter"] = "gender_filter"
    options: List[ActionOption]

class AgeFilterQuestion(BaseQuestion):
    question_type: Literal["age_filter"] = "age_filter"
    options: List[ActionOption]

class Predicate(BaseModel):
    qid: str
    field: Optional[str] = None
    op: Literal[
        "eq","ne","contains","matches",
        "contains_any","contains_all",
        "lt","le","gt","ge","between"
    ]
    value: Any

class Rule(BaseModel):
    when: List[Predicate]
    then: Action

class ConditionalQuestion(BaseQuestion):
    question_type: Literal["conditional"] = "conditional"
    rules: List[Rule]
    default: Optional[Action] = None

Question = Annotated[
    Union[
        FreeTextQuestion,
        FreeTextWithFieldQuestion,
        NumberRangeQuestion,
        SingleSelectQuestion,
        MultiSelectQuestion,
        ImageSelectQuestion,
        GenderQuestion,
        AgeFilterQuestion,
        ConditionalQuestion,
    ],
    Field(discriminator="question_type"),
]

question_mapper = {
    "free_text": FreeTextQuestion,
    "free_text_with_fields": FreeTextWithFieldQuestion,
    "number_range": NumberRangeQuestion,
    "single_select": SingleSelectQuestion,
    "multi_select": MultiSelectQuestion,
    "image_single_select": ImageSelectQuestion,
    "gender_filter": GenderQuestion,
    "age_filter": AgeFilterQuestion,
    "conditional": ConditionalQuestion
}