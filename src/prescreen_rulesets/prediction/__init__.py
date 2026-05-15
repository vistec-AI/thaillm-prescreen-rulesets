"""Concrete PredictionModule implementations.

Provides:
  - ``OpenAIPredictionModule`` — uses the OpenAI chat completions API with
    structured (JSON schema) output.
  - ``MedgemmaPredictionModule`` — uses a self-hosted vLLM endpoint serving
    ``google/medgemma-27b-text-it``, parsing the model's XML answer.

Both produce differential diagnosis, department routing, and severity
assessment as a ``PredictionResult``.
"""

from prescreen_rulesets.prediction.medgemma import MedgemmaPredictionModule
from prescreen_rulesets.prediction.openai import OpenAIPredictionModule

__all__ = ["OpenAIPredictionModule", "MedgemmaPredictionModule"]
