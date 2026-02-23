"""Server configuration — reads settings from environment variables.

All settings have sensible defaults for local development.  In production
the values are typically overridden via env vars or a ``.env`` file.
"""

import os
from dataclasses import dataclass, field

# --- Pagination & cleanup defaults ---
# Module-level constants read at import time so FastAPI Query() defaults
# can reference them (Query defaults must be static at decoration time).
DEFAULT_PAGE_LIMIT = int(os.getenv("DEFAULT_PAGE_LIMIT", "20"))
MAX_PAGE_LIMIT = int(os.getenv("MAX_PAGE_LIMIT", "100"))
DEFAULT_CLEANUP_DAYS = int(os.getenv("DEFAULT_CLEANUP_DAYS", "90"))


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

    # Session TTL — default age threshold (days) for cleanup operations.
    # 0 means infinite (no automatic cleanup unless explicitly requested).
    session_ttl_days: int = 0

    # Admin API key — shared secret for admin endpoints (None = disabled)
    admin_api_key: str | None = None

    # Trusted proxy secret — when set, every request that carries
    # X-User-ID must also carry X-Proxy-Secret matching this value.
    # This ensures the user identity header was injected by a trusted
    # API gateway and not forged by an external client.
    trusted_proxy_secret: str | None = None


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
        session_ttl_days=int(os.getenv("SESSION_TTL_DAYS", "0")),
        admin_api_key=os.getenv("ADMIN_API_KEY") or None,
        trusted_proxy_secret=os.getenv("TRUSTED_PROXY_SECRET") or None,
    )
