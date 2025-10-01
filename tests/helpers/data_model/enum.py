from enum import Enum


class ChoiceStatus(str, Enum):
    TERMINATE = "terminate"
    NEXT = "next"


class QuestionType(str, Enum):
    # responsive
    FREE_TEXT = "free_text"
    FREE_TEXT_WITH_FIELDS = "free_text_with_fields"
    NUMBER_RANGE = "number_range"
    SINGLE_SELECT = "single_select"
    MULTI_SELECT = "multi_select"
    IMAGE_SINGLE_SELECT = "image_single_select"
    IMAGE_MULTI_SELECT = "image_multi_select"
    # auto
    GENDER = "gender_filter"
    AGE_FILTER = "age_filter"
    CONDITIONAL = "conditional"