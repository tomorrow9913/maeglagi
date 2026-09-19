"""Grouped thin MCP tool registrations."""

from mcp.server import MCPServer

from app.core.config import Settings


def register_tools(server: MCPServer, settings: Settings) -> None:
    from app.mcp.tools import analysis, directory, knowledge, sources, workspaces

    workspaces.register(server, settings)
    sources.register(server, settings)
    analysis.register(server, settings)
    knowledge.register(server, settings)
    directory.register(server, settings)
