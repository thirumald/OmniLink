"""Expose OmniLink read tools over the Model Context Protocol (MCP Python SDK, MIT).

Run:  OMNILINK_TOKEN=<user or service token> python -m omnilink_assistant.mcp_server
Write tools are intentionally NOT exposed over MCP: proposals need the console approval flow.
"""

from __future__ import annotations

import os

from .llm import OpenAICompatibleLLM
from .platform import PlatformClient
from .rag import MemoryKnowledgeBase
from .tools import TOOLS, ToolContext


def build_server():  # pragma: no cover - requires the mcp package
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("omnilink")
    ctx = ToolContext(os.environ.get("OMNILINK_TENANT", "abudhabi"), "mcp", {"viewer"},
                      PlatformClient(os.environ["OMNILINK_TOKEN"]), MemoryKnowledgeBase(OpenAICompatibleLLM()))

    def register(tool):
        async def handler(**kwargs):
            return await tool.run(ctx, kwargs)

        handler.__name__ = tool.name
        handler.__doc__ = tool.description
        mcp.add_tool(handler, name=tool.name, description=tool.description)

    for t in TOOLS.values():
        if not t.write:
            register(t)
    return mcp


if __name__ == "__main__":  # pragma: no cover
    build_server().run()
