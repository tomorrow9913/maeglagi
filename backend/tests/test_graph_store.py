from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore


def test_neo4j_requires_all_environment_variables() -> None:
    assert not Settings(
        _env_file=None, neo4j_uri="neo4j+s://example", neo4j_username="neo4j"
    ).neo4j_enabled
    assert Settings(
        _env_file=None,
        neo4j_uri="neo4j+s://example",
        neo4j_username="neo4j",
        neo4j_password="secret",
    ).neo4j_enabled


@pytest.mark.asyncio
async def test_graph_store_normalizes_records_and_closes_driver() -> None:
    first = MagicMock()
    first.data.return_value = {"id": "entity-1"}
    second = MagicMock()
    second.data.return_value = {"id": "entity-2"}
    driver = AsyncMock()
    driver.execute_query.return_value = ([first, second], object(), object())
    store = Neo4jGraphStore(driver)

    result = await store.execute("MATCH (e:Entity) RETURN e", {"workspace_id": "w1"})
    await store.verify_connectivity()
    await store.close()

    assert result == [{"id": "entity-1"}, {"id": "entity-2"}]
    driver.execute_query.assert_awaited_once_with(
        "MATCH (e:Entity) RETURN e", parameters_={"workspace_id": "w1"}
    )
    driver.verify_connectivity.assert_awaited_once()
    driver.close.assert_awaited_once()
