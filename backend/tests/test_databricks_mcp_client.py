"""G10 — real MCP client tests plus the new chat.py fallback branch.

Per this task's own instructions: the real-integration tests below exercise
the actual live Databricks Managed MCP endpoint (HTTP + MCP handshake +
`Config(profile="lakebridge-eval").authenticate()` auth) end-to-end. The
mocked ones at the bottom are explicitly NOT real integration tests — there
is currently no Unity Catalog function registered in
TARGET_CATALOG.TARGET_SCHEMA, so the "tool found" paths can't be exercised
against the real workspace yet. They monkeypatch only at the
`chat.databricks_mcp_client.list_tools_sync` boundary (the same "mock only
the outermost real-transport call" style already used elsewhere in this
test suite for slow/unavailable real dependencies), never fabricating
`mcp` internals.
"""
import pytest
from fastapi.testclient import TestClient

from app import chat
from app.databricks_target import TARGET_CATALOG, TARGET_SCHEMA
from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Real integration tests — actual live workspace, no mocking.
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_list_tools_sync_real_endpoint_returns_without_raising():
    """Proves the real HTTP + MCP-handshake + auth path genuinely works.

    Asserts the *handshake*, not the presence of one particular function. It
    used to require `mcp_fallback_ping` to be registered, which coupled a
    protocol test to the contents of the demo target schema — that schema is
    deliberately kept to a handful of objects so a demo migration is visibly
    new, and pruning it broke this test for a reason that had nothing to do
    with MCP. Any UC function registering as a tool proves the same path; an
    empty schema is also a legitimate real state, so that is not a failure
    either. What must never happen is raising.
    """
    from app.databricks_mcp_client import list_tools_sync

    result = list_tools_sync(TARGET_CATALOG, TARGET_SCHEMA)
    assert isinstance(result, list)
    assert all(isinstance(t.get("name"), str) for t in result)


def test_chat_plan_databricks_mcp_fallback_disabled_by_default_returns_fast(monkeypatch):
    """G12: the MCP fallback is disabled by default (DATABRICKS_MCP_FALLBACK_ENABLED
    = False). Once G9's real table resolution genuinely can't resolve the
    instruction (mocked here at the `_find_matching_databricks_table`
    boundary so this test isn't at the mercy of real Databricks SQL
    warehouse cold-start latency, which is a separate, real, pre-existing
    cost unrelated to this toggle — confirmed directly: a real run of this
    same instruction took ~179s just to enumerate catalogs before ever
    reaching the MCP-disabled check), the disabled branch must refuse
    immediately with the disabled-reason message and must NEVER call the
    real MCP client (`databricks_mcp_client.list_tools_sync`) — proving no
    additional 78-120s+ MCP round trip is incurred on top of table
    resolution."""
    import time

    assert chat.DATABRICKS_MCP_FALLBACK_ENABLED is False

    monkeypatch.setattr(chat, "_find_matching_databricks_table", lambda text: ("none", None))

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("MCP fallback must not be reached while DATABRICKS_MCP_FALLBACK_ENABLED is False")

    monkeypatch.setattr(chat.databricks_mcp_client, "list_tools_sync", _fail_if_called)

    start = time.time()
    r = client.post(
        "/chat/plan",
        json={"instruction": "show me the totally_made_up_table_xyz_123 table in databricks"},
    )
    elapsed = time.time() - start
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert body["reason"] == "the databricks mcp fallback is temporarily disabled"
    assert "action" not in body
    assert elapsed < 5.0


@pytest.mark.slow
def test_chat_plan_databricks_fallback_reaches_real_mcp_branch_honestly_when_enabled(monkeypatch):
    """Same real-integration scenario as before G12, but explicitly
    re-enabling the flag for this test only — proves the underlying G10
    branch logic is untouched and still genuinely reachable/functional,
    just gated off by default now."""
    monkeypatch.setattr(chat, "DATABRICKS_MCP_FALLBACK_ENABLED", True)
    r = client.post(
        "/chat/plan",
        json={"instruction": "show me the totally_made_up_table_xyz_123 table in databricks"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "reason" in body
    reason = body["reason"].lower()
    assert "no mcp tools" in reason or "not registered" in reason or "mcp" in reason
    assert TARGET_CATALOG in body["reason"] and TARGET_SCHEMA in body["reason"]


# ---------------------------------------------------------------------------
# Narrower unit tests — NOT real integration tests. Monkeypatch only at the
# `chat.databricks_mcp_client.list_tools_sync` transport boundary, since no
# real UC function exists yet to exercise these paths for real.
# ---------------------------------------------------------------------------


def _databricks_unresolvable_instruction() -> str:
    # Matches _DATABRICKS_KEYWORD_RE but not any real table, so
    # _find_matching_databricks_table returns "none" and falls through.
    return "show me the totally_made_up_table_xyz_123 table in databricks"


def test_mcp_fallback_single_zero_arg_tool_match_builds_plan(monkeypatch):
    monkeypatch.setattr(chat, "DATABRICKS_MCP_FALLBACK_ENABLED", True)
    tools = [{"name": "totally_made_up_table_xyz_123", "description": "d", "input_schema": {}}]
    monkeypatch.setattr(chat.databricks_mcp_client, "list_tools_sync", lambda catalog, schema: tools)

    r = client.post("/chat/plan", json={"instruction": _databricks_unresolvable_instruction()})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is True
    assert body["action"] == {
        "kind": "databricks_mcp_tool",
        "catalog": TARGET_CATALOG,
        "schema": TARGET_SCHEMA,
        "tool_name": "totally_made_up_table_xyz_123",
        "arguments": {},
    }


def test_mcp_fallback_tool_requiring_arguments_is_refused_with_specific_reason(monkeypatch):
    monkeypatch.setattr(chat, "DATABRICKS_MCP_FALLBACK_ENABLED", True)
    tools = [
        {
            "name": "totally_made_up_table_xyz_123",
            "description": "d",
            "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": ["limit"]},
        }
    ]
    monkeypatch.setattr(chat.databricks_mcp_client, "list_tools_sync", lambda catalog, schema: tools)

    r = client.post("/chat/plan", json={"instruction": _databricks_unresolvable_instruction()})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "requires arguments" in body["reason"]
    assert "limit" in body["reason"]
    assert "action" not in body


def test_mcp_fallback_multiple_matches_refused_as_ambiguous(monkeypatch):
    monkeypatch.setattr(chat, "DATABRICKS_MCP_FALLBACK_ENABLED", True)
    tools = [
        {"name": "totally_made_up_table_xyz_123", "description": "d", "input_schema": {}},
        {"name": "made_up_table_xyz_123", "description": "d", "input_schema": {}},
    ]
    monkeypatch.setattr(chat.databricks_mcp_client, "list_tools_sync", lambda catalog, schema: tools)

    r = client.post("/chat/plan", json={"instruction": _databricks_unresolvable_instruction()})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is False
    assert "more than one" in body["reason"]
    assert "action" not in body
