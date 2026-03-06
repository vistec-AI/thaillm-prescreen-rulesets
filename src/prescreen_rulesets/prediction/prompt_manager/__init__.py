"""Prompt management for the OpenAI prediction module.

Provides ``PredictionPromptManager``, a Jinja2-based renderer that
builds system and user prompts for the LLM prediction call.
"""

from prescreen_rulesets.prediction.prompt_manager.prompt_manager import (
    PredictionPromptManager,
)

__all__ = ["PredictionPromptManager"]
