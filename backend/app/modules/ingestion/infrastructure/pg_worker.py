"""Run the durable PostgreSQL ingestion executor without an HTTP server.

Usage: PROCESSING_EXECUTOR=postgres python -m app.modules.ingestion.infrastructure.pg_worker
"""

import asyncio
import signal

from app.core.config import Settings, get_settings
from app.core.observability import configure_observability
from app.modules.ingestion.infrastructure.pg_executor import PostgresExecutor


async def run_worker(
    settings: Settings | None = None, *, stop_event: asyncio.Event | None = None
) -> None:
    settings = settings or get_settings()
    if settings.processing_executor != "postgres":
        raise ValueError("Standalone worker requires PROCESSING_EXECUTOR=postgres")
    configure_observability(settings)

    stopped = stop_event if stop_event is not None else asyncio.Event()
    loop = asyncio.get_running_loop()
    installed_signals: list[signal.Signals] = []
    if stop_event is None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, stopped.set)
            except NotImplementedError:
                # Signal handlers are available on the Linux deployment target.
                continue
            installed_signals.append(signum)

    executor = PostgresExecutor(settings)
    try:
        executor.start()
        await stopped.wait()
    finally:
        await executor.stop()
        for signum in installed_signals:
            loop.remove_signal_handler(signum)


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
