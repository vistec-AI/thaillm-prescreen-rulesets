"""Concrete QuestionGenerator implementations.

Provides ``OpenAIQuestionGenerator``, an LLM-backed generator that uses the
OpenAI chat completions API to produce follow-up prescreening questions.
"""

from prescreen_rulesets.question_generator.openai import OpenAIQuestionGenerator

__all__ = ["OpenAIQuestionGenerator"]
