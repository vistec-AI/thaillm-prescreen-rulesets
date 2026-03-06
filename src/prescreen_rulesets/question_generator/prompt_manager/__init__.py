"""Prompt management for the OpenAI question generator.

Provides ``QuestionGeneratorPromptManager``, a Jinja2-based renderer that
builds system and user prompts from QA history for the LLM.
"""

from prescreen_rulesets.question_generator.prompt_manager.prompt_manager import (
    QuestionGeneratorPromptManager,
)

__all__ = ["QuestionGeneratorPromptManager"]
