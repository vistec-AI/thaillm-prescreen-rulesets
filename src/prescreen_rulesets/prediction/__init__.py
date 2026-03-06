"""Concrete PredictionModule implementations.

Provides ``OpenAIPredictionModule``, an LLM-backed prediction module that uses
the OpenAI chat completions API with structured output to produce differential
diagnosis, department routing, and severity assessment.
"""

from prescreen_rulesets.prediction.openai import OpenAIPredictionModule

__all__ = ["OpenAIPredictionModule"]
