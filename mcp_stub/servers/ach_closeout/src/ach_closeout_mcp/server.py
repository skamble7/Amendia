# server.py
"""Streamable-HTTP MCP app exposing the ACH-exposure **Closeout** segment tools (streamable HTTP at ``/mcp``)."""
from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .handlers import TOOLS, TOOLS_BY_NAME, check_compliance

logger = logging.getLogger(__name__)

SERVER_NAME = "ach-closeout"
DEFAULT_PORT = "8077"


def build_server() -> Server:
    check_compliance()  # refuse to build a non-compliant server
    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["input_schema"],
                outputSchema=t["output_schema"],
            )
            for t in TOOLS
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict):
        spec = TOOLS_BY_NAME.get(name)
        if spec is None:
            raise ValueError(f"unknown tool: {name}")
        result = spec["handler"](arguments or {})
        return [types.TextContent(type="text", text=json.dumps(result))], result

    return server


def create_app() -> Starlette:
    server = build_server()
    session_manager = StreamableHTTPSessionManager(
        app=server, event_store=None, json_response=True, stateless=True
    )

    async def handle_mcp(scope, receive, send) -> None:
        await session_manager.handle_request(scope, receive, send)

    async def health(_request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": SERVER_NAME, "tools": len(TOOLS)})

    @asynccontextmanager
    async def lifespan(_app):
        async with session_manager.run():
            logger.info("%s MCP server ready — %d tools at /mcp (streamable HTTP)", SERVER_NAME, len(TOOLS))
            yield

    return Starlette(
        debug=False,
        lifespan=lifespan,
        routes=[Route("/health", health), Mount("/mcp", app=handle_mcp)],
    )


def main() -> None:
    import uvicorn

    logging.basicConfig(level=os.environ.get("MCP_LOG_LEVEL", "INFO"))
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT") or os.environ.get("PORT") or DEFAULT_PORT)
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
