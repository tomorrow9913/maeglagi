from collections.abc import Mapping
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.core.config import Settings, get_settings


class Neo4jGraphStore:
    """Async Neo4j adapter shared by API, workers, and readiness checks."""

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "Neo4jGraphStore":
        settings = settings or get_settings()
        if not settings.neo4j_enabled:
            raise ValueError("Neo4j environment variables are not configured")
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password.get_secret_value()),
        )
        return cls(driver)

    async def verify_connectivity(self) -> None:
        await self._driver.verify_connectivity()

    async def execute(
        self, query: str, parameters: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        records, _, _ = await self._driver.execute_query(query, parameters_=parameters or {})
        return [record.data() for record in records]

    async def close(self) -> None:
        await self._driver.close()
