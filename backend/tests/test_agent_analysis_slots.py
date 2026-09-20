import asyncio
from uuid import uuid4

from app.modules.agent_workflows.locks import _analysis_slot, _local_gates


async def test_unrelated_workspace_proceeds_while_conflicting_waiters_wait():
    workspace_a, workspace_b = uuid4(), uuid4()
    started = asyncio.Event()
    release = asyncio.Event()
    blocked_entries = []

    async def holder():
        async with _analysis_slot(workspace_a):
            started.set()
            await release.wait()

    async def waiter():
        async with _analysis_slot(workspace_a):
            blocked_entries.append(True)

    holder_task = asyncio.create_task(holder())
    await started.wait()
    waiters = [asyncio.create_task(waiter()) for _ in range(6)]
    await asyncio.sleep(0)
    try:
        async with asyncio.timeout(1):
            async with _analysis_slot(workspace_b):
                assert not blocked_entries
    finally:
        release.set()
        await asyncio.gather(holder_task, *waiters)
    assert len(blocked_entries) == 6
    assert asyncio.get_running_loop() not in _local_gates


async def test_cancelled_waiter_does_not_leak_a_slot_or_event_loop():
    workspace = uuid4()

    async def waiter():
        async with _analysis_slot(workspace):
            raise AssertionError("conflicting waiter entered")

    async with _analysis_slot(workspace):
        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        task.cancel()
        result = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
    assert asyncio.get_running_loop() not in _local_gates
