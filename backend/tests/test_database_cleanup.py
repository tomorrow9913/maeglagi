"""Cancellation must never strand request-owned database connections."""

import asyncio

import pytest

from app.core import database


@pytest.mark.asyncio
async def test_session_scope_finishes_close_before_propagating_cancellation(monkeypatch) -> None:
    close_started = asyncio.Event()
    allow_close = asyncio.Event()

    class Session:
        async def close(self) -> None:
            close_started.set()
            await allow_close.wait()

    session = Session()
    monkeypatch.setattr(database, "session_factory", lambda: session)

    async def request() -> None:
        async with database.session_scope():
            await asyncio.Event().wait()

    task = asyncio.create_task(request())
    await asyncio.sleep(0)
    task.cancel()
    await close_started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    allow_close.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_session_scope_closes_after_handler_exception(monkeypatch) -> None:
    closed = False

    class Session:
        async def close(self) -> None:
            nonlocal closed
            closed = True

    monkeypatch.setattr(database, "session_factory", Session)
    with pytest.raises(RuntimeError, match="handler failed"):
        async with database.session_scope():
            raise RuntimeError("handler failed")
    assert closed
