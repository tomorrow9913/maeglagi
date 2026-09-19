"""Minimal Hybrid Retrieval (TSK-33): vector search + graph expansion + Context Store.

Query understanding here is deterministic, not an LLM call: the question itself is the semantic
query, and the entities it *names* (matched against the graph's normalized keys) are what the
graph is walked from. The graph then widens the evidence to the sources those entities and their
two-hop neighbours came from.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.modules.context_engine.application.entity_resolution import normalize_name
from app.modules.context_engine.infrastructure.models import Chunk
from app.modules.retrieval.domain.answer import AnswerSource
from app.modules.retrieval.infrastructure.graph_neighborhood import GraphNeighborhood
from app.modules.workspaces.infrastructure.models import Source

logger = logging.getLogger(__name__)

SearchFn = Callable[[str, list[UUID] | None, int], Awaitable[list[tuple[Chunk, float]]]]
LoadSources = Callable[[list[UUID]], Awaitable[dict[UUID, Source]]]

EXCERPT_CHARS = 300
MIN_KEY_CHARS = 2  # a one-letter key would match almost any question


@dataclass
class Evidence:
    source: AnswerSource
    text: str


@dataclass
class GraphFact:
    source: str
    kind: str
    target: str
    superseded: list[str] = field(default_factory=list)


@dataclass
class QueryPlan:
    semantic_query: str
    entities: list[dict[str, Any]]  # the graph entities the question names


@dataclass
class RetrievalResult:
    evidence: list[Evidence]
    facts: list[GraphFact]
    entities: list[str]


def understand_query(question: str, graph_entities: list[dict[str, Any]]) -> QueryPlan:
    """Split a question into what to search by meaning and which entities to walk from."""
    normalized = normalize_name(question, "Event")
    named = [
        entity
        for entity in graph_entities
        if any(len(key) >= MIN_KEY_CHARS and key in normalized for key in entity["keys"])
    ]
    return QueryPlan(semantic_query=question.strip(), entities=named)


class HybridRetriever:
    def __init__(
        self,
        *,
        search: SearchFn,
        load_sources: LoadSources,
        graph: GraphNeighborhood | None = None,
        vector_limit: int = 6,
        graph_limit: int = 4,
        max_evidence: int = 8,
    ) -> None:
        self.search = search
        self.load_sources = load_sources
        self.graph = graph
        self.vector_limit = vector_limit
        self.graph_limit = graph_limit
        self.max_evidence = max_evidence

    async def retrieve(
        self, workspace_id: UUID, question: str, *, now: datetime | None = None
    ) -> RetrievalResult:
        hits = await self.search(question, None, self.vector_limit)
        facts: list[GraphFact] = []
        entity_names: list[str] = []

        graph_sources = await self._graph_sources(workspace_id, question, now, facts, entity_names)
        if graph_sources:
            hits += await self.search(question, graph_sources, self.graph_limit)

        chunks: dict[UUID, Chunk] = {}
        for chunk, _ in hits:  # vector hits first, graph-scoped ones after; first sighting wins
            chunks.setdefault(chunk.id, chunk)
        ordered = list(chunks.values())[: self.max_evidence]
        sources = await self.load_sources(list({c.source_id for c in ordered})) if ordered else {}

        # A chunk whose source is gone is not evidence; numbering stays contiguous without it.
        evidence = [
            Evidence(
                source=AnswerSource(
                    index=index,
                    source_id=chunk.source_id,
                    chunk_id=chunk.id,
                    kind=sources[chunk.source_id].kind,
                    title=sources[chunk.source_id].title,
                    excerpt=chunk.content.strip()[:EXCERPT_CHARS],
                    timestamp=chunk.start_seconds,
                ),
                text=chunk.content.strip(),
            )
            for index, chunk in enumerate((c for c in ordered if c.source_id in sources), start=1)
        ]
        return RetrievalResult(evidence=evidence, facts=facts, entities=entity_names)

    async def _graph_sources(
        self,
        workspace_id: UUID,
        question: str,
        now: datetime | None,
        facts: list[GraphFact],
        entity_names: list[str],
    ) -> list[UUID]:
        """Walk the graph from the entities the question names; return the sources it points to.

        The graph only widens the search. If it is unreachable the answer still comes from
        vector search, so its failures are logged, not raised.
        """
        if self.graph is None:
            return []
        try:
            plan = understand_query(question, await self.graph.entities(workspace_id))
            if not plan.entities:
                return []
            keys = sorted({key for entity in plan.entities for key in entity["keys"]})
            rows = await self.graph.facts(workspace_id, keys, now or datetime.now(UTC))
        except Exception:
            logger.warning(
                "graph expansion failed; answering from vector search only", exc_info=True
            )
            return []

        entity_names.extend(entity["name"] for entity in plan.entities)
        facts.extend(
            GraphFact(
                source=row["source"],
                kind=row["kind"],
                target=row["target"],
                superseded=list(row.get("superseded") or []),
            )
            for row in rows
        )
        wanted = {
            *(i for entity in plan.entities for i in entity["source_ids"]),
            *(i for row in rows for i in row["source_ids"]),
        }
        valid: list[UUID] = []
        for identifier in sorted(wanted):
            try:
                valid.append(UUID(str(identifier)))
            except ValueError:
                continue
        return valid
