"""Real MCP client for the Databricks Managed MCP (Unity Catalog Functions)
endpoint — G10's third chat fallback.

Endpoint shape and transport confirmed against Databricks' own docs and the
real `mcp` Python SDK installed in this project's venv (`mcp==2.0.0`):
`https://<workspace-hostname>/api/2.0/mcp/functions/{catalog}/{schema}`,
Streamable HTTP transport (`mcp.client.streamable_http.streamable_http_client`
+ `mcp.client.session.ClientSession`).

Deliberately mirrors `databricks_target.py`'s auth pattern rather than
inventing new config: same `Config(profile="lakebridge-eval")`, same
`_WAREHOUSE_HOSTNAME`, same `TargetError`-style per-module exception
(`DatabricksMCPError`) as `connectors/starburst.py`'s `ConnectorError` /
`connectors/databricks_browse.py`'s `BrowseError`.

`list_tools`/`call_tool` are the real async MCP calls; `list_tools_sync`/
`call_tool_sync` are thin `asyncio.run(...)` wrappers because `chat.py` is
invoked from FastAPI's sync request path (same reasoning as every other
sync wrapper in this codebase).
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx2
from databricks.sdk.core import Config
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .databricks_target import _WAREHOUSE_HOSTNAME
from .redact import redact


class DatabricksMCPError(RuntimeError):
    pass


def _mcp_url(catalog: str, schema: str) -> str:
    return f"https://{_WAREHOUSE_HOSTNAME}/api/2.0/mcp/functions/{catalog}/{schema}"


def _auth_headers() -> dict[str, str]:
    try:
        from .executor import databricks_config

        cfg = databricks_config()
        return cfg.authenticate()
    except Exception as exc:  # noqa: BLE001
        raise DatabricksMCPError(redact(str(exc))) from exc


async def list_tools(catalog: str, schema: str) -> list[dict]:
    """Real MCP `initialize` + `list_tools()` against the real workspace.
    Returns tools as plain dicts (name/description/input_schema) — never
    fabricated, an empty list is the honest real answer when no Unity
    Catalog function is registered in `catalog.schema`."""
    url = _mcp_url(catalog, schema)
    try:
        headers = _auth_headers()
        async with httpx2.AsyncClient(headers=headers) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return [
                        {
                            "name": t.name,
                            "description": t.description,
                            "input_schema": t.input_schema,
                        }
                        for t in result.tools
                    ]
    except DatabricksMCPError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DatabricksMCPError(redact(str(exc))) from exc


async def call_tool(catalog: str, schema: str, tool_name: str, arguments: dict) -> Any:
    """Real MCP `call_tool` against the real workspace."""
    url = _mcp_url(catalog, schema)
    try:
        headers = _auth_headers()
        async with httpx2.AsyncClient(headers=headers) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    return result
    except DatabricksMCPError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DatabricksMCPError(redact(str(exc))) from exc


def list_tools_sync(catalog: str, schema: str) -> list[dict]:
    return asyncio.run(list_tools(catalog, schema))


def call_tool_sync(catalog: str, schema: str, tool_name: str, arguments: dict) -> Any:
    return asyncio.run(call_tool(catalog, schema, tool_name, arguments))
