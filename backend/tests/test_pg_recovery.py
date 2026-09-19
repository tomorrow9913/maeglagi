"""Run recovery against isolated tables in a disposable loopback PostgreSQL."""

import asyncio
import os
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.modules.ingestion.infrastructure.pg_recovery import recover_missing_jobs


@pytest.fixture
async def recovery_db():
    url = os.environ.get("PG_EXECUTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set PG_EXECUTOR_TEST_DATABASE_URL to a disposable loopback database")
    assert urlparse(url).hostname in {"localhost", "127.0.0.1", "::1"}
    schema = f"recovery_{uuid4().hex}"
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text("""
            CREATE TABLE sources (
                id uuid PRIMARY KEY, kind text, status text, review_state text,
                processing_stage text NOT NULL
            )
        """))
        await connection.execute(text("""
            CREATE TABLE processing_jobs (
                source_id uuid PRIMARY KEY REFERENCES sources(id), status text,
                stage text, provider_attempts integer, claim_generation integer,
                next_run_at timestamptz, created_at timestamptz, updated_at timestamptz
            )
        """))
    yield async_sessionmaker(engine, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()


async def seed(factory, *, kind="meeting", status="queued", review="confirmed"):
    identifier = uuid4()
    async with factory() as session:
        await session.execute(
            text("""INSERT INTO sources VALUES (:id, :kind, :status, :review, 'confirmed')"""),
            {"id": identifier, "kind": kind, "status": status, "review": review},
        )
        await session.commit()
    return identifier


async def test_recovery_respects_review_gate_and_terminal_states(recovery_db):
    eligible = {
        await seed(recovery_db),
        await seed(recovery_db, status="processing", review="transcribing"),
        await seed(recovery_db, kind="document", status="enqueue_pending", review=None),
    }
    await seed(recovery_db, review="awaiting_review")
    await seed(recovery_db, review=None)
    for state in ("failed", "succeeded", "awaiting_review"):
        await seed(recovery_db, status=state)
    async with recovery_db() as session:
        assert await recover_missing_jobs(session) == 3
        await session.commit()
        found = (await session.execute(text("SELECT source_id FROM processing_jobs"))).scalars()
        assert set(found) == eligible


async def test_recovery_is_idempotent_and_preserves_existing_jobs(recovery_db):
    identifier = await seed(recovery_db)
    async with recovery_db() as session:
        assert await recover_missing_jobs(session) == 1
        await session.execute(text("""
            UPDATE processing_jobs SET status='failed', provider_attempts=4, claim_generation=8
        """))
        await session.commit()
        assert await recover_missing_jobs(session) == 0
        row = (await session.execute(text("""
            SELECT source_id, status, provider_attempts, claim_generation FROM processing_jobs
        """))).one()
        assert tuple(row) == (identifier, "failed", 4, 8)


async def test_recovery_rolls_back_and_concurrent_starts_deduplicate(recovery_db):
    await seed(recovery_db)
    async with recovery_db() as session:
        assert await recover_missing_jobs(session) == 1
        await session.rollback()

    async def run():
        async with recovery_db() as session:
            count = await recover_missing_jobs(session)
            await session.commit()
            return count

    assert sum(await asyncio.gather(run(), run())) == 1
