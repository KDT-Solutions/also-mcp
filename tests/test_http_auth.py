"""HTTP endpoint protection: bearer token on every path except GET /healthz."""

import importlib
import os
import sys

import pytest
import respx
from starlette.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

API_KEY = "test-mcp-api-key"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", API_KEY)
    monkeypatch.setenv("ALSO_API_USER", "api.user@example.com")
    monkeypatch.setenv("ALSO_API_PASSWORD", "test-password")
    from also_marketplace_mcp import server as srv

    return importlib.reload(srv)


@pytest.fixture
def http_client(server):
    with TestClient(server._build_http_app(), base_url="https://mcp.example.com") as client:
        yield client


def init_request():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
    }


def test_healthz_without_token_is_200(http_client):
    with respx.mock(assert_all_mocked=True) as upstream:
        resp = http_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    # no call to the ALSO API
    assert upstream.calls.call_count == 0


def test_mcp_without_token_is_401(http_client):
    resp = http_client.post("/mcp", json=init_request(), headers=HEADERS)
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}


@pytest.mark.parametrize("auth", ["Bearer wrong", f"bearer {API_KEY}", API_KEY, "Basic abc"])
def test_mcp_wrong_token_is_401(http_client, auth):
    resp = http_client.post("/mcp", json=init_request(), headers={**HEADERS, "Authorization": auth})
    assert resp.status_code == 401


def test_mcp_valid_token_passes(http_client):
    resp = http_client.post("/mcp", json=init_request(), headers={**HEADERS, "Authorization": f"Bearer {API_KEY}"})
    assert resp.status_code == 200
    assert resp.json()["result"]["serverInfo"]["name"]


@pytest.mark.parametrize("path", ["/healthz/", "/healthzx", "/mcp/healthz", "/"])
def test_other_paths_still_need_token(http_client, path):
    assert http_client.get(path).status_code == 401


def test_healthz_only_get(http_client):
    assert http_client.post("/healthz").status_code == 401
