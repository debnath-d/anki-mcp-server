"""Anki Model Context Protocol (MCP) Server."""

from __future__ import annotations

from anki_mcp_server.server import server


def main() -> None:
    """Run the Anki MCP Server over stdio."""
    server.run(transport="stdio")


__all__ = ["main", "server"]
