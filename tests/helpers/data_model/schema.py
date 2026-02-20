"""Re-export schema models from the SDK.

Canonical definitions now live in ``prescreen_rulesets.models.schema``.
This file re-exports the legacy names so existing test imports continue working.
"""

from prescreen_rulesets.models.schema import (  # noqa: F401
    Department,
    Disease,
    NHSOSymptoms,
    SeverityLevel,
)
