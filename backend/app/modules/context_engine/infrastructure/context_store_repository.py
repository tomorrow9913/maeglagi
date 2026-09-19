from uuid import UUID

from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.modules.context_engine.infrastructure.models import ContextRecord, ContextStoreRecord


class SqlContextStoreRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load(self, workspace_id: UUID) -> ContextStoreRecord | None:
        # FOR UPDATE: two sources of one workspace must not overwrite each other's update.
        result = await self.session.exec(
            select(ContextStoreRecord)
            .where(ContextStoreRecord.workspace_id == workspace_id)
            .with_for_update()
        )
        return result.first()

    async def save(self, record: ContextStoreRecord) -> None:
        self.session.add(record)

    async def replace_timeline(self, source_id: UUID, rows: list[ContextRecord]) -> None:
        """Reprocessing a source replaces its timeline rows instead of duplicating them."""
        await self.session.execute(
            delete(ContextRecord).where(ContextRecord.source_id == source_id)
        )
        self.session.add_all(rows)
