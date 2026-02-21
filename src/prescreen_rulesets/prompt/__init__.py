"""Prompt rendering for LLM players.

Provides ``PromptManager``, a Jinja2-based template engine that renders
``QuestionsStep`` objects into LLM-ready prompt strings with JSON response
format instructions.
"""

from prescreen_rulesets.prompt.manager import PromptManager

__all__ = ["PromptManager"]
