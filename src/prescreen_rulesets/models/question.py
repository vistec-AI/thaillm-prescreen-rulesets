"""Question type models for prescreening decision trees.

Each question type maps to a specific UI component and answer handling logic:

  User-facing (shown to the patient):
    - free_text: open-ended text input
    - free_text_with_fields: text input with structured sub-fields
    - number_range: numeric slider/input with min/max/step
    - single_select: pick one option (each option has its own action)
    - multi_select: pick one or more options (single "next" action)
    - image_single_select: single_select with an image
    - image_multi_select: multi_select with an image

  Auto-evaluated (resolved by the engine, never shown to users):
    - gender_filter: routes based on patient gender from demographics
    - age_filter: routes based on patient age from demographics
    - conditional: evaluates predicate rules against prior answers

The discriminated ``Question`` union uses ``question_type`` as its discriminator.
The ``question_mapper`` dict maps type strings to their Pydantic classes.
"""

from __future__ import annotations

from typing import Any, Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from .action import Action


# --- Base question type ---

class BaseQuestion(BaseModel):
    """Fields shared by all question types."""

    qid: str
    question: str

    @property
    def is_oldcarts(self) -> bool:
        """True if this question belongs to the OLDCARTS phase (no '_opd_' in qid)."""
        return "_opd_" not in self.qid

    @property
    def oldcarts_state(self) -> Optional[Literal["o", "l", "d", "c", "a", "r", "t", "s", "as"]]:
        """The OLDCARTS mnemonic letter extracted from the qid's middle segment.

        Returns None for non-OLDCARTS questions. The qid convention is
        ``{prefix}_{letter}_{number}`` where letter is the OLDCARTS state.
        """
        if not self.is_oldcarts:
            return None
        return self.qid.split("_")[1]


# --- Shared option/field models ---

class Option(BaseModel):
    """A selectable option with an id and display label."""

    id: str
    label: str


class ActionOption(Option):
    """An option that carries its own action (used in single_select and image_single_select)."""

    action: Action


class TextField(BaseModel):
    """A sub-field for free_text_with_fields questions."""

    id: str
    label: str
    kind: Literal["text"]


# --- User-facing question types ---

class FreeTextQuestion(BaseQuestion):
    """Open-ended text input."""

    question_type: Literal["free_text"] = "free_text"
    on_submit: Action


class FreeTextWithFieldQuestion(BaseQuestion):
    """Text input with structured sub-fields (e.g. medication name + dosage)."""

    question_type: Literal["free_text_with_fields"] = "free_text_with_fields"
    fields: List[TextField]
    on_submit: Action


class NumberRangeQuestion(BaseQuestion):
    """Numeric slider/input with min/max/step constraints."""

    question_type: Literal["number_range"] = "number_range"
    min_value: float
    max_value: float
    step: float = 1.0
    default_value: Optional[float] = None
    on_submit: Action

    @model_validator(mode="after")
    def _chk(self):
        if self.min_value >= self.max_value:
            raise ValueError("min_value must be < max_value")
        # Default to min_value if not explicitly provided
        if self.default_value is None:
            self.default_value = self.min_value
        return self


class SingleSelectQuestion(BaseQuestion):
    """Pick one option; each option carries its own action."""

    question_type: Literal["single_select"] = "single_select"
    options: List[ActionOption]


class MultiSelectQuestion(BaseQuestion):
    """Pick one or more options; a single "next" action is used regardless of selection."""

    question_type: Literal["multi_select"] = "multi_select"
    options: List[Option]
    next: Action


class ImageHotspot(Option):
    """An option with an optional image reference (for image-based questions)."""

    image: Optional[str] = None


class ImageSelectQuestion(BaseQuestion):
    """Single-select with an image; each option carries its own action."""

    question_type: Literal["image_single_select"] = "image_single_select"
    image: str
    options: List[ActionOption]


class ImageMultiSelectQuestion(BaseQuestion):
    """Multi-select with an image; a single "next" action is used."""

    question_type: Literal["image_multi_select"] = "image_multi_select"
    image: str
    options: List[Option]
    next: Action


# --- Auto-evaluated question types (never shown to users) ---

class GenderQuestion(BaseQuestion):
    """Routes based on patient gender; resolved automatically by the engine."""

    question_type: Literal["gender_filter"] = "gender_filter"
    options: List[ActionOption]


class AgeFilterQuestion(BaseQuestion):
    """Routes based on patient age; resolved automatically by the engine."""

    question_type: Literal["age_filter"] = "age_filter"
    options: List[ActionOption]


# --- Conditional logic models ---

class Predicate(BaseModel):
    """A single condition that references a prior answer.

    Operators:
      - eq, ne: equality / inequality
      - lt, le, gt, ge: numeric comparisons
      - between: value is [min, max] inclusive
      - contains, not_contains: substring / element membership
      - contains_any, contains_all: set membership
      - matches: regex match
    """

    qid: str
    field: Optional[str] = None
    op: Literal[
        "eq", "ne", "contains", "not_contains", "matches",
        "contains_any", "contains_all",
        "lt", "le", "gt", "ge", "between",
    ]
    value: Any


class Rule(BaseModel):
    """A conditional rule: if ALL predicates in ``when`` are true, fire ``then``."""

    when: List[Predicate]
    then: Action


class ConditionalQuestion(BaseQuestion):
    """Evaluates predicate rules against prior answers; resolved automatically.

    Rules are evaluated in order; the first matching rule's ``then`` action fires.
    If no rule matches and ``default`` is set, that action fires instead.
    """

    question_type: Literal["conditional"] = "conditional"
    rules: List[Rule]
    default: Optional[Action] = None


# --- Discriminated union of all question types ---

Question = Annotated[
    Union[
        FreeTextQuestion,
        FreeTextWithFieldQuestion,
        NumberRangeQuestion,
        SingleSelectQuestion,
        MultiSelectQuestion,
        ImageSelectQuestion,
        ImageMultiSelectQuestion,
        GenderQuestion,
        AgeFilterQuestion,
        ConditionalQuestion,
    ],
    Field(discriminator="question_type"),
]

# Maps question_type string → Pydantic class for dynamic deserialization from YAML.
question_mapper = {
    "free_text": FreeTextQuestion,
    "free_text_with_fields": FreeTextWithFieldQuestion,
    "number_range": NumberRangeQuestion,
    "single_select": SingleSelectQuestion,
    "multi_select": MultiSelectQuestion,
    "image_single_select": ImageSelectQuestion,
    "image_multi_select": ImageMultiSelectQuestion,
    "gender_filter": GenderQuestion,
    "age_filter": AgeFilterQuestion,
    "conditional": ConditionalQuestion,
}
