"""Recover accepted sources stranded before the PostgreSQL executor was enabled."""

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession


async def recover_missing_jobs(session: AsyncSession) -> int:
    """Insert missing schedules without reopening completed jobs or review gates.

    The caller commits. Existing jobs, including failed/cancelled jobs, retain
    their retry budget and lease. Concurrent executors can safely run this once
    on startup; source execution locks still serialize any legacy worker.
    """
    result = await session.execute(
        text("""
            INSERT INTO processing_jobs (
                source_id, status, stage, provider_attempts, claim_generation,
                next_run_at, created_at, updated_at
            )
            SELECT s.id, 'pending', s.processing_stage, 0, 0, now(), now(), now()
            FROM sources AS s
            WHERE s.analysis_mode = 'server'
              AND s.status IN ('queued', 'processing', 'enqueue_pending')
              AND (
                s.kind = 'document'
                OR (s.kind = 'meeting' AND s.review_state IN ('confirmed', 'transcribing'))
              )
              AND NOT EXISTS (SELECT 1 FROM processing_jobs AS j WHERE j.source_id = s.id)
            ON CONFLICT (source_id) DO NOTHING
            RETURNING source_id
        """)
    )
    return len(result.all())
