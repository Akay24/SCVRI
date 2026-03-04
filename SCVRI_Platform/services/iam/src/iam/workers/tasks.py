"""IAM Celery tasks — session and token housekeeping."""
from __future__ import annotations

import asyncio

from celery.utils.log import get_task_logger

from iam.workers.celery_app import celery_app

log = get_task_logger(__name__)


@celery_app.task(
    name="iam.workers.tasks.purge_expired_sessions_task",
    queue="celery",
)
def purge_expired_sessions_task() -> dict:
    """
    Daily housekeeping: remove any expired password-reset or MFA session records
    from the DB (Redis TTLs handle token storage automatically).
    """
    async def _run() -> int:
        from sqlalchemy import text  # noqa: PLC0415
        from scvri_shared.database import get_engine  # noqa: PLC0415

        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                DELETE FROM iam.password_reset_tokens
                WHERE expires_at < now()
            """))
            return result.rowcount

    deleted = asyncio.run(_run())
    log.info(f"purge_expired_sessions.complete deleted={deleted}")
    return {"deleted": deleted}
