"""TTL / archival CLI — ``prescreen-cleanup``.

Provides a standalone command that connects to the database and runs bulk
session cleanup operations.  Intended for cron jobs or one-off maintenance.

Default behaviour: soft-delete completed/terminated sessions older than 90
days.

Examples::

    # Soft-delete all completed/terminated sessions (default --days 0 = all)
    uv run prescreen-cleanup

    # Soft-delete completed/terminated sessions older than 90 days
    uv run prescreen-cleanup --days 90

    # Permanently delete sessions older than 30 days
    uv run prescreen-cleanup --days 30 --hard

    # Purge all soft-deleted rows
    uv run prescreen-cleanup --purge-deleted

    # Purge soft-deleted rows older than 7 days
    uv run prescreen-cleanup --purge-deleted --days 7

    # Only target completed and terminated sessions
    uv run prescreen-cleanup --status completed --status terminated
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)


async def run_cleanup(
    *,
    days: int = int(os.getenv("DEFAULT_CLEANUP_DAYS", "90")),
    status_filter: list[str] | None = None,
    hard: bool = False,
    purge_deleted: bool = False,
) -> int:
    """Execute the cleanup operation and return the number of affected rows.

    Creates its own database session, runs the repository bulk methods,
    and commits.  Safe to call from a CLI entry point or a scheduled task.
    """
    # Lazy imports to avoid loading DB machinery at module import time
    from prescreen_db.engine import dispose_engine, get_session_factory
    from prescreen_db.repository import SessionRepository

    repo = SessionRepository()
    factory = get_session_factory()

    try:
        async with factory() as db:
            if purge_deleted:
                affected = await repo.purge_soft_deleted(
                    db, older_than_days=days,
                )
                action = "purge_soft_deleted"
            else:
                # Default status filter: completed and terminated sessions
                if status_filter is None:
                    status_filter = ["completed", "terminated"]
                affected = await repo.bulk_purge_old_sessions(
                    db,
                    older_than_days=days,
                    status_filter=status_filter,
                    hard=hard,
                )
                action = "hard_delete" if hard else "soft_delete"

            await db.commit()

        logger.info(
            "Cleanup complete: action=%s, affected_rows=%d, days=%d",
            action, affected, days,
        )
        return affected
    finally:
        await dispose_engine()


def cli() -> None:
    """Console-script entry point: ``prescreen-cleanup``.

    Parses command-line arguments and runs the async cleanup function.
    """
    parser = argparse.ArgumentParser(
        prog="prescreen-cleanup",
        description="Clean up old prescreen sessions from the database.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.getenv("DEFAULT_CLEANUP_DAYS", os.getenv("SESSION_TTL_DAYS", "90"))),
        help=(
            "Age threshold in days (default: $DEFAULT_CLEANUP_DAYS, "
            "falling back to $SESSION_TTL_DAYS, or 90). "
            "0 means no age filter — affects all matching sessions."
        ),
    )
    parser.add_argument(
        "--status",
        action="append",
        default=None,
        help=(
            "Only target sessions with this status (repeatable). "
            "Default: completed, terminated"
        ),
    )
    parser.add_argument(
        "--hard",
        action="store_true",
        default=False,
        help="Permanently DELETE rows instead of soft-deleting",
    )
    parser.add_argument(
        "--purge-deleted",
        action="store_true",
        default=False,
        help="Purge previously soft-deleted rows (ignores --status/--hard)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    affected = asyncio.run(
        run_cleanup(
            days=args.days,
            status_filter=args.status,
            hard=args.hard,
            purge_deleted=args.purge_deleted,
        )
    )

    print(f"Affected rows: {affected}")
    sys.exit(0)
