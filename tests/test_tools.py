"""Write guard (confirm + MCP_READONLY), also_raw_call allowlist/validation, audit log, client error handling."""

import importlib
import json
import os
import sys

import httpx
import pytest
import respx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

BASE = "https://marketplace.example.com/SimpleAPI/SimpleAPIService.svc/rest"


@pytest.fixture
def srv(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "x" * 32)
    monkeypatch.setenv("ALSO_API_USER", "api.user@example.com")
    monkeypatch.setenv("ALSO_API_PASSWORD", "test-password")
    monkeypatch.setenv("ALSO_BASE_URL", BASE)
    monkeypatch.delenv("MCP_READONLY", raising=False)
    from also_marketplace_mcp import server

    server = importlib.reload(server)
    # No real ALSO calls: record what would be sent instead.
    calls = []

    def fake_call(endpoint, body=None):
        calls.append((endpoint, body))
        return {"ok": True}

    monkeypatch.setattr(server, "_call", fake_call)
    monkeypatch.setattr(server, "_resolve_account_id", lambda account_id: account_id if account_id is not None else 1)
    server._test_calls = calls
    return server


def _audit_lines(capsys):
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


# ---------------------------------------------------------------------------
# also_raw_call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("endpoint", ["GetCreditLimit", "GetReports", "ListSomething", "ValidateFields"])
def test_raw_call_read_endpoint_without_confirm(srv, endpoint, capsys):
    assert srv.also_raw_call(endpoint, {"a": 1}) == {"ok": True}
    assert srv._test_calls == [(endpoint, {"a": 1})]
    assert _audit_lines(capsys) == []  # reads are not audited


@pytest.mark.parametrize("endpoint", ["SetSpecialDeal", "TerminateAccount", "CreateSubscription", "getCompany"])
def test_raw_call_write_endpoint_requires_confirm(srv, endpoint, capsys):
    res = srv.also_raw_call(endpoint, {"a": 1})
    assert "confirm=true" in res["error"]
    assert srv._test_calls == []
    (line,) = _audit_lines(capsys)
    assert line["tool"] == "also_raw_call" and line["status"] == "refused"


def test_raw_call_getaway_is_still_a_read(srv):
    # "Get..." prefix is what makes it a read; "Getaway2" above is matched by the regex too.
    assert srv._is_read_endpoint("Getaway2") is True
    assert srv._is_read_endpoint("SetSpecialDeal") is False
    assert srv._is_read_endpoint("getCompany") is False  # case-sensitive like the ALSO API


def test_raw_call_write_with_confirm_is_executed_and_audited(srv, capsys):
    res = srv.also_raw_call("SetSpecialDeal", {"accountId": 5, "Password": "geheim"}, confirm=True)
    assert res == {"ok": True}
    assert srv._test_calls == [("SetSpecialDeal", {"accountId": 5, "Password": "geheim"})]
    (line,) = _audit_lines(capsys)
    assert line["status"] == "ok" and line["params"]["endpoint"] == "SetSpecialDeal"
    assert line["params"]["body"]["Password"] == "***" and "geheim" not in json.dumps(line)


@pytest.mark.parametrize("endpoint", ["", "../GetCompany", "GetCompany/../x", "https://evil.example.com/x",
                                      "Get Company", "GetCompany?x=1", "1abc", "A" * 101, None, 42])
def test_raw_call_rejects_invalid_endpoint(srv, endpoint):
    res = srv.also_raw_call(endpoint, confirm=True)
    assert "Invalid endpoint" in res["error"]
    assert srv._test_calls == []


# ---------------------------------------------------------------------------
# MCP_READONLY
# ---------------------------------------------------------------------------


def test_readonly_blocks_all_write_tools(srv, monkeypatch, capsys):
    monkeypatch.setenv("MCP_READONLY", "true")
    results = [
        srv.also_create_company(1, {"CompanyName": "x"}, confirm=True),
        srv.also_create_user(1, "a@example.com", "A", "B", confirm=True),
        srv.also_create_subscription(1, "svc", {}, confirm=True),
        srv.also_update_subscription(2, "svc", 1, {}, confirm=True),
        srv.also_execute_subscription_upgrade(2, "svc2", {}, confirm=True),
        srv.also_terminate_account(2, confirm=True),
        srv.also_raw_call("SetSpecialDeal", {}, confirm=True),
    ]
    for res in results:
        assert "MCP_READONLY" in res["error"]
    assert srv._test_calls == []
    lines = _audit_lines(capsys)
    assert len(lines) == 7 and all(l["status"] == "refused" and l["detail"] == "MCP_READONLY" for l in lines)
    assert {l["tool"] for l in lines} == {
        "also_create_company", "also_create_user", "also_create_subscription", "also_update_subscription",
        "also_execute_subscription_upgrade", "also_terminate_account", "also_raw_call",
    }


def test_readonly_keeps_reads_working(srv, monkeypatch):
    monkeypatch.setenv("MCP_READONLY", "true")
    assert srv.also_get_subscriptions(1) == {"ok": True}
    assert srv.also_raw_call("GetCreditLimit") == {"ok": True}


@pytest.mark.parametrize("value", ["false", "0", "", "no"])
def test_readonly_off_values(srv, monkeypatch, value):
    monkeypatch.setenv("MCP_READONLY", value)
    assert srv._readonly() is False


# ---------------------------------------------------------------------------
# confirm + audit log on the dedicated write tools
# ---------------------------------------------------------------------------


def test_terminate_without_confirm_is_refused_and_audited(srv, capsys):
    res = srv.also_terminate_account(99, "no longer needed")
    assert "confirm=true" in res["error"]
    assert srv._test_calls == []
    (line,) = _audit_lines(capsys)
    assert line == {**line, "tool": "also_terminate_account", "status": "refused", "detail": "confirm missing",
                    "params": {"account_id": 99, "termination_reason": "no longer needed"}}
    assert line["audit"] == "also-mcp" and line["ts"].endswith("+00:00")


def test_create_subscription_audit_redacts_secrets(srv, capsys):
    fields = {"Domain": "example.com", "AdminPassword": "s3cret", "Nested": {"ApiToken": "t", "Count": 2}}
    assert srv.also_create_subscription(7, "O365", fields, confirm=True) == {"ok": True}
    (line,) = _audit_lines(capsys)
    assert line["status"] == "ok"
    assert line["params"]["fields"] == {"Domain": "example.com", "AdminPassword": "***",
                                        "Nested": {"ApiToken": "***", "Count": 2}}
    assert "s3cret" not in json.dumps(line)
    # the real call still gets the unredacted fields
    assert srv._test_calls[0][1]["subscriptionAccount"]["Fields"]["AdminPassword"] == "s3cret"


def test_write_error_is_audited_as_error(srv, monkeypatch, capsys):
    monkeypatch.setattr(srv, "_call", lambda endpoint, body=None: {"error": "TerminateAccount failed (400): nope"})
    assert "error" in srv.also_terminate_account(1, confirm=True)
    (line,) = _audit_lines(capsys)
    assert line["status"] == "error" and "nope" in line["detail"]


# ---------------------------------------------------------------------------
# Startup checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["", "short", "a" * 31])
def test_main_refuses_short_api_key(srv, monkeypatch, key):
    monkeypatch.setattr(srv, "_MCP_API_KEY", key)
    with pytest.raises(RuntimeError, match="32 characters"):
        srv.main()


# ---------------------------------------------------------------------------
# Client: XML fault parsing (defusedxml) and connection errors
# ---------------------------------------------------------------------------


def test_parse_xml_fault_plain():
    from also_marketplace_mcp.client import _parse_xml_fault

    assert _parse_xml_fault("<Fault><Message>Access denied</Message></Fault>") == "Access denied"
    assert _parse_xml_fault("not xml at all") == "not xml at all"


def test_parse_xml_fault_rejects_entities_and_huge_bodies():
    from also_marketplace_mcp.client import _MAX_FAULT_BODY, _parse_xml_fault

    bomb = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
            "<Fault><Message>&b;</Message></Fault>")
    # defusedxml refuses entity expansion; the raw body comes back instead of an expanded string
    assert "aaaaaaaaaa" not in _parse_xml_fault(bomb).replace(bomb, "")
    assert _parse_xml_fault("<x>" * (_MAX_FAULT_BODY // 3 + 1)).startswith("Error body too large")


def test_connection_error_is_clean_also_api_error():
    from also_marketplace_mcp.client import AlsoApiError, AlsoMarketplaceClient

    client = AlsoMarketplaceClient(BASE, "u", "p")
    with respx.mock(base_url=BASE) as mock:
        mock.post("/GetSessionToken").mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(AlsoApiError) as exc:
            client.call("GetCompany", {})
    msg = str(exc.value)
    assert "ConnectError" in msg and "marketplace.example.com" not in msg and "boom" not in msg


def test_server_call_returns_error_dict_on_connection_failure(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "x" * 32)
    monkeypatch.setenv("ALSO_API_USER", "api.user@example.com")
    monkeypatch.setenv("ALSO_API_PASSWORD", "test-password")
    monkeypatch.setenv("ALSO_BASE_URL", BASE)
    from also_marketplace_mcp import server

    server = importlib.reload(server)
    with respx.mock(base_url=BASE) as mock:
        mock.post("/GetSessionToken").mock(side_effect=httpx.ReadTimeout("slow"))
        res = server.also_get_company()
    assert "ReadTimeout" in res["error"] and "example.com" not in res["error"]
