"""
Direct MCP client calls (no LLM) used by the rule-based executor and the
web interface. Every order still goes through our local trading MCP server.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

ROOT = Path(__file__).resolve().parent.parent
MARKET_SERVER = str(ROOT / "servers" / "market_data_mcp_server.py")
TRADING_SERVER = str(ROOT / "servers" / "alpaca_trading_mcp_server.py")


def server_env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env.setdefault("PYTHONWARNINGS", "ignore")
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update({k: v for k, v in extra.items() if v})
    return env


def _parse(result):
    data = getattr(result, "data", None)
    if data is not None:
        if hasattr(data, "result"):          # str-returning tools are wrapped
            data = data.result
        if isinstance(data, str):
            try:
                return json.loads(data)
            except ValueError:
                return data
        return data
    texts = [c.text for c in (result.content or []) if getattr(c, "text", None)]
    raw = "\n".join(texts)
    try:
        return json.loads(raw)
    except ValueError:
        return raw


async def _call_many(server: str, calls: list[tuple[str, dict]], env: dict | None):
    transport = PythonStdioTransport(server, env=server_env(env), python_cmd=sys.executable)
    out = []
    async with Client(transport) as c:
        for name, args in calls:
            try:
                out.append(_parse(await c.call_tool(name, args)))
            except Exception as e:  # report per call, keep going
                out.append({"error": f"{type(e).__name__}: {e}"})
    return out


def call_many(server: str, calls: list[tuple[str, dict]], env: dict | None = None) -> list:
    """Run several tool calls on one server session; returns parsed results in order."""
    return asyncio.run(_call_many(server, calls, env))


def call(server: str, tool: str, args: dict | None = None, env: dict | None = None):
    return call_many(server, [(tool, args or {})], env)[0]
