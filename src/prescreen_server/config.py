"""Server configuration — reads settings from environment variables.

All settings have sensible defaults for local development.  In production
the values are typically overridden via env vars or a ``.env`` file.
"""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServerSettings:
    """Immutable server configuration read from environment at startup."""

    # Network
    host: str = "0.0.0.0"
    port: int = 8080

    # CORS — comma-separated origins, or "*" for wide-open dev mode
    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    # Ruleset directory (None → RulesetStore default, which is v1/ from repo root)
    ruleset_dir: str | None = None

    # Logging
    log_level: str = "INFO"


def load_settings() -> ServerSettings:
    """Build settings from ``SERVER_*`` environment variables."""
    raw_origins = os.getenv("SERVER_CORS_ORIGINS", "*")
    origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

    return ServerSettings(
        host=os.getenv("SERVER_HOST", "0.0.0.0"),
        port=int(os.getenv("SERVER_PORT", "8080")),
        cors_origins=origins,
        ruleset_dir=os.getenv("SERVER_RULESET_DIR") or None,
        log_level=os.getenv("SERVER_LOG_LEVEL", "INFO").upper(),
    )
