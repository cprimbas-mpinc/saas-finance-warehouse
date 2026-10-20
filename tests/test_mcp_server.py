"""The MCP server, exercised through a real MCP client over an in-memory transport."""

from __future__ import annotations

import asyncio
import json

import pytest
from mcp.client.client import Client

EXPECTED_TOOLS = {"ask", "list_metrics", "describe_metric", "query_metrics", "list_saved_queries",
                  "run_saved_query", "get_control_status", "run_sql"}


@pytest.fixture(scope="module")
def server(seeded, monkeypatch_module):
    monkeypatch_module.setenv("WAREHOUSE_PATH", str(seeded / "warehouse.duckdb"))
    from finance_semantic import server as srv
    srv.layer.cache_clear()
    yield srv.mcp
    srv.layer.cache_clear()


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def call(server, tool: str, args: dict) -> dict:
    async def go():
        async with Client(server) as client:
            result = await client.call_tool(tool, args)
            assert not result.is_error, result
            return json.loads(result.content[0].text)
    return asyncio.run(go())


def test_server_lists_read_only_tools(server):
    async def go():
        async with Client(server) as client:
            return (await client.list_tools()).tools
    tools = asyncio.run(go())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)


def test_ask_over_mcp(server):
    out = call(server, "ask", {"question": "NRR by segment"})
    assert {r["segment"] for r in out["rows"]} == {"Enterprise", "Mid-Market", "SMB"}
    assert out["sql"].startswith("with ")


def test_structured_query_over_mcp(server):
    out = call(server, "query_metrics", {"metrics": ["arr", "paying_customers"], "grain": "quarter",
                                         "last_n_periods": 4})
    assert [r["period"] for r in out["rows"]] == ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]


def test_saved_query_and_controls_over_mcp(server):
    assert call(server, "run_saved_query", {"name": "arr_bridge"})["row_count"] == 12
    assert "of 8 controls passed" in call(server, "get_control_status", {})["summary"]


def test_errors_come_back_as_messages_not_crashes(server):
    assert "Unknown metric" in call(server, "query_metrics", {"metrics": ["ebitda"]})["error"]
    assert "Only a single read-only SELECT" in call(server, "run_sql", {"sql": "drop table dim_customers"})["error"]
