from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.modules.retrieval.infrastructure.graph_reader import GraphReader
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


@pytest.mark.asyncio
async def test_graph_pages_use_unique_order_tiebreakers() -> None:
    store = AsyncMock()
    store.execute.return_value = []
    reader = GraphReader(store)
    workspace_id = uuid4()
    at = datetime(2026, 9, 20, tzinfo=UTC)

    await reader.nodes_page(workspace_id, limit=1, offset=0)
    await reader.nodes_page(workspace_id, limit=1, offset=1)
    await reader.edges_page(workspace_id, at, limit=1, offset=0)
    await reader.edges_page(workspace_id, at, limit=1, offset=1)

    node_first, node_second, edge_first, edge_second = store.execute.await_args_list
    assert node_first.args[0] == node_second.args[0]
    assert "ORDER BY e.name, e.id\n\nSKIP $offset LIMIT $limit" in node_first.args[0]
    assert node_first.args[1] == {"workspace_id": str(workspace_id), "offset": 0, "limit": 1}
    assert node_second.args[1]["offset"] == 1

    assert edge_first.args[0] == edge_second.args[0]
    assert (
        "ORDER BY a.name, a.id, kind, b.name, b.id, r.id, elementId(r)\n\nSKIP $offset LIMIT $limit"
    ) in edge_first.args[0]
    assert edge_first.args[1]["at"] == at.isoformat()
    assert edge_first.args[1]["offset"] == 0
    assert edge_second.args[1]["offset"] == 1
