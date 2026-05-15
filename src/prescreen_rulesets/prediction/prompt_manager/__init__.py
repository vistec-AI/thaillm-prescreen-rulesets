"""Prompt management for the prediction modules.

Provides:
  - ``PredictionPromptManager`` — Jinja2 renderer for the OpenAI prediction
    module (phase-grouped JSON prompt with reference tables).
  - ``MedgemmaPromptManager`` — Jinja2 renderer for the medgemma-prescreen
    connector (structured patient profile + conversation transcript).
"""

from prescreen_rulesets.prediction.prompt_manager.medgemma_prompt_manager import (
    MedgemmaPromptManager,
)
from prescreen_rulesets.prediction.prompt_manager.prompt_manager import (
    PredictionPromptManager,
)

__all__ = ["PredictionPromptManager", "MedgemmaPromptManager"]
