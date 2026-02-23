"""Global exception handlers — map SDK exceptions to HTTP status codes.

The SDK raises ``ValueError`` for various conditions (session not found,
wrong stage, duplicate session).  Rather than catching these in every route,
we install global handlers that inspect the message and pick the right HTTP
status code.  This keeps route handlers clean and focused on the happy path.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# --- Keyword patterns in ValueError messages and their HTTP status codes ---
# Checked in order; first match wins.
_VALUE_ERROR_PATTERNS: list[tuple[str, int]] = [
    # Session already exists (unique constraint on user_id + session_id)
    ("already exists", 409),
    # Session not found
    ("not found", 404),
    # Wrong pipeline stage (e.g. submit_answer during llm_questioning)
    ("only valid during", 400),
]


# --- Client-safe messages keyed by HTTP status code ---
# Internal details (user_id, session_id, stage names) stay in the server
# log; the client receives only a generic description.
_SAFE_MESSAGES: dict[int, str] = {
    404: "Resource not found",
    409: "Resource already exists",
    400: "Invalid request",
}


async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Map SDK ``ValueError`` to a contextual HTTP error response.

    Inspects the exception message to decide between 404 (not found),
    409 (conflict / duplicate), or 400 (bad request / wrong stage).
    Falls back to 400 for unrecognised messages.

    The raw exception message is logged server-side but **never** sent
    to the client — it may contain user_id, session_id, or internal
    pipeline stage names.
    """
    msg = str(exc)
    status = 400  # default
    for pattern, code in _VALUE_ERROR_PATTERNS:
        if pattern in msg.lower():
            status = code
            break

    # Full detail stays server-side; client gets a safe generic message.
    logger.warning("ValueError [%d] at %s: %s", status, request.url, msg)
    safe_detail = _SAFE_MESSAGES.get(status, "Invalid request")
    return JSONResponse(status_code=status, content={"detail": safe_detail})


async def key_error_handler(request: Request, exc: KeyError) -> JSONResponse:
    """Map ``KeyError`` (e.g. unknown department/severity ID) to 404."""
    logger.warning("KeyError at %s: %s", request.url, exc)
    return JSONResponse(status_code=404, content={"detail": "Resource not found"})


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions — log full traceback, return 500."""
    logger.exception("Unhandled exception at %s", request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
