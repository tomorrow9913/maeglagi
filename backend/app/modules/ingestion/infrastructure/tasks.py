"""Celery adapter for the shared source processor."""

import asyncio
from uuid import UUID

from celery import Task

from app.core.celery import celery_app
from app.modules.ingestion.infrastructure.source_processor import process_source_attempt


@celery_app.task(
    bind=True,
    name="ingestion.process_source",
    max_retries=3,
    default_retry_delay=10,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def process_source(self: Task, source_id: str, app_attempt: int = 0) -> None:
    identifier = UUID(source_id)
    final_attempt = app_attempt >= self.max_retries
    try:
        error = asyncio.run(process_source_attempt(identifier, final_attempt=final_attempt))
    except Exception as exc:
        # The lock/DB connection failed; leave source state untouched and keep
        # retrying infrastructure recovery. The normal three-attempt provider
        # bound below must not acknowledge a persisted `processing` source.
        raise self.retry(
            exc=exc,
            countdown=30,
            max_retries=2_147_483_647,
            kwargs={"app_attempt": app_attempt},
        ) from exc
    if error is not None:
        if final_attempt:
            raise error
        raise self.retry(
            exc=error,
            max_retries=2_147_483_647,
            kwargs={"app_attempt": app_attempt + 1},
        ) from error
