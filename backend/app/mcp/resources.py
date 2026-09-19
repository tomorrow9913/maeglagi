"""Small, stable reference resources for external agents."""

import json

from mcp.server import MCPServer

from app.modules.context_engine.domain.ontology import ContextKind, EntityKind, RelationKind


def register_resources(server: MCPServer) -> None:
    @server.resource(
        "maeglagi://ontology/schema",
        name="ontology_schema",
        description="Allowed entity, relationship, and context kinds for grounded analysis.",
        mime_type="application/json",
    )
    def ontology_schema() -> str:
        return json.dumps(
            {
                "entityKinds": [kind.value for kind in EntityKind],
                "relationKinds": [kind.value for kind in RelationKind],
                "contextKinds": [kind.value for kind in ContextKind],
                "evidenceRule": (
                    "Every extracted claim must cite a source and a supporting passage."
                ),
            },
            ensure_ascii=False,
        )
