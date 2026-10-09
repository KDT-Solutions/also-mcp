"""
MCP server exposing the ALSO Cloud Marketplace SimpleAPI as tools.

Configuration (environment variables):
  ALSO_API_USER      - required. Username of the ALSO API user (not MFA-enabled).
  ALSO_API_PASSWORD  - required. Password for that user.
  ALSO_BASE_URL      - optional. Defaults to the Swiss production endpoint.

  MCP_TRANSPORT      - "stdio" (default, local) or "http" (Cloud/Docker).
  MCP_HOST           - bind address for http mode (default 0.0.0.0).
  MCP_PORT           - port for http mode (default 8000).
  MCP_API_KEY        - required when MCP_TRANSPORT=http. Static bearer token;
                        every request must send "Authorization: Bearer <token>".
                        The server refuses to start in http mode without it -
                        same convention as KDT's other MCP servers
                        (zammad-mcp, plesk-mcp): never expose this over the
                        network unauthenticated, not even "briefly".

Every write/mutating tool (create/update/terminate/upgrade) requires an
explicit confirm=true argument, mirroring the pattern used in KDT's other
MCP servers (e.g. plesk-mcp's DNS record tools). Read-only tools never
require confirmation. confirm=true is a safety rail against accidental
calls, not a security boundary - MCP_API_KEY is what actually gates access.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from .client import DEFAULT_BASE_URL, AlsoApiError, AlsoMarketplaceClient

# Version = <major.minor>.<patch>. major.minor is maintained by hand in
# pyproject.toml, the patch part counts automatically: the number of commits
# that changed a build-relevant file (package, pyproject.toml, Dockerfile,
# workflow). In the Docker image GitHub Actions sets the final version as
# APP_VERSION; in a local git checkout it is computed from the git history.
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VERSION_PATHS = ["Dockerfile", "pyproject.toml", "src/", ".github/workflows/docker-publish.yml"]


def _version_base() -> str:
    """major.minor from pyproject.toml (checkout), else from the installed package metadata."""
    raw = ""
    try:
        import tomllib
        with open(os.path.join(_REPO_DIR, "pyproject.toml"), "rb") as f:
            raw = tomllib.load(f)["project"]["version"]
    except Exception:
        try:
            from importlib.metadata import version
            raw = version("also-marketplace-mcp")
        except Exception:
            pass
    return ".".join(raw.split(".")[:2]) if raw else "0.0"


def _read_version() -> str:
    env_version = os.environ.get("APP_VERSION", "").strip()
    if env_version:
        return env_version
    base = _version_base()
    try:
        import subprocess
        count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD", "--", *_VERSION_PATHS],
            cwd=_REPO_DIR, capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        if count.isdigit():
            return f"{base}.{count}"
    except Exception:
        pass
    return f"{base}.0-dev"


__version__ = _read_version()

mcp = MCPServer("also-marketplace", version=__version__)

# HTTP mode: MCP_TRANSPORT=http (Cloud/Docker) instead of stdio (local, default).
_HTTP_MODE = os.environ.get("MCP_TRANSPORT", "stdio").lower() in ("http", "streamable-http")
_HTTP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
_HTTP_PORT = int(os.environ.get("MCP_PORT", "8000"))
_MCP_API_KEY = os.environ.get("MCP_API_KEY", "")

if _HTTP_MODE and not _MCP_API_KEY:
    raise RuntimeError(
        "MCP_TRANSPORT=http requires MCP_API_KEY (a static bearer token) - "
        "refusing to start without it for security reasons."
    )

_client: AlsoMarketplaceClient | None = None


def _get_client() -> AlsoMarketplaceClient:
    global _client
    if _client is None:
        username = os.environ.get("ALSO_API_USER")
        password = os.environ.get("ALSO_API_PASSWORD")
        if not username or not password:
            raise AlsoApiError(
                "ALSO_API_USER / ALSO_API_PASSWORD are not set. Configure them as "
                "environment variables for this container."
            )
        base_url = os.environ.get("ALSO_BASE_URL", DEFAULT_BASE_URL)
        _client = AlsoMarketplaceClient(base_url=base_url, username=username, password=password)
    return _client


def _call(endpoint: str, body: dict[str, Any] | None = None) -> Any:
    try:
        return _get_client().call(endpoint, body)
    except AlsoApiError as exc:
        # Surface a clean, plain-text error to the model/user instead of a stack trace.
        return {"error": str(exc)}


def _require_confirm(confirm: bool, action: str) -> dict[str, Any] | None:
    if not confirm:
        return {
            "error": (
                f"Refused: {action} is a write operation. Call again with confirm=true "
                "to actually execute it."
            )
        }
    return None


# ---------------------------------------------------------------------------
# Server info
# ---------------------------------------------------------------------------


@mcp.tool()
def get_version() -> dict[str, str]:
    """Version and build commit of the running ALSO MCP server (to verify a redeploy)."""
    return {"name": "also-mcp", "version": __version__, "commit": os.environ.get("GIT_SHA", "unknown")}


# ---------------------------------------------------------------------------
# Companies / resellers / departments / users
# ---------------------------------------------------------------------------


@mcp.tool()
def also_get_company(account_id: int | None = None) -> Any:
    """Get one company/account by its ALSO account ID. Omit account_id to get your own account."""
    body = {"accountId": account_id} if account_id is not None else {}
    return _call("GetCompany", body)


@mcp.tool()
def also_get_companies(parent_account_id: int) -> Any:
    """List all companies (customers) under a parent account ID."""
    return _call("GetCompanies", {"parentAccountId": parent_account_id})


@mcp.tool()
def also_get_company_by_vat_id(vat_id: str) -> Any:
    """Look up a company by its VAT ID."""
    return _call("GetCompanyByVatId", {"vatId": vat_id})


@mcp.tool()
def also_create_company(parent_account_id: int, company_account: dict[str, Any], confirm: bool = False) -> Any:
    """
    Create a new company/customer under parent_account_id.

    company_account: dict of the ALSO "companyAccount" fields (e.g. CompanyName,
    Address, PostalCode, City, Country, Email, VatId, ...). Field names follow
    the ALSO SimpleAPI Swagger spec (PascalCase) - verify against a real
    GetCompany response if a field is rejected.

    Requires confirm=true.
    """
    if (err := _require_confirm(confirm, "creating a company")) is not None:
        return err
    payload = {"parentAccountId": parent_account_id, "companyAccount": company_account}
    return _call("CreateCompany", payload)


@mcp.tool()
def also_get_users(company_account_id: int) -> Any:
    """List users under a company account."""
    return _call("GetUsers", {"companyAccountId": company_account_id})


@mcp.tool()
def also_create_user(parent_account_id: int, email: str, first_name: str, last_name: str, confirm: bool = False) -> Any:
    """Create a new user under a company/parent account. Requires confirm=true."""
    if (err := _require_confirm(confirm, "creating a user")) is not None:
        return err
    payload = {
        "userAccount": {
            "ParentAccountId": parent_account_id,
            "Email": email,
            "FirstName": first_name,
            "LastName": last_name,
        }
    }
    return _call("CreateUser", payload)


# ---------------------------------------------------------------------------
# Catalog / service discovery
# ---------------------------------------------------------------------------


@mcp.tool()
def also_get_possible_services(parent_account_id: int) -> Any:
    """List services/products that can be booked (subscribed to) for a given customer account."""
    return _call("GetPossibleServicesForParent", {"parentAccountId": parent_account_id})


@mcp.tool()
def also_get_fields_for_service(parent_account_id: int, product_name: str, secondary_parent_id: int | None = None) -> Any:
    """
    Get the input fields required to create a subscription for product_name
    (the ProductName/ServiceName as returned by also_get_possible_services).
    """
    body: dict[str, Any] = {"parentAccountId": parent_account_id, "productName": product_name}
    if secondary_parent_id is not None:
        body["secondaryParentId"] = secondary_parent_id
    return _call("GetFieldsForService", body)


@mcp.tool()
def also_validate_fields(
    parent_account_id: int,
    service_name: str,
    fields: dict[str, Any],
    fields_to_validate: list[str] | None = None,
    account_id: int | None = None,
) -> Any:
    """Validate subscription field values before calling also_create_subscription."""
    subscription_account: dict[str, Any] = {
        "ParentAccountId": parent_account_id,
        "ServiceName": service_name,
        "Fields": fields,
    }
    if account_id is not None:
        subscription_account["AccountId"] = account_id
    body: dict[str, Any] = {"subscriptionAccount": subscription_account}
    if fields_to_validate:
        body["subscriptionAccount"]["FieldsToValidate"] = fields_to_validate
    return _call("ValidateFields", body)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


@mcp.tool()
def also_get_subscription(account_id: int, reseller_context: int | None = None) -> Any:
    """Get a single subscription by its account ID."""
    body: dict[str, Any] = {"accountId": account_id}
    if reseller_context is not None:
        body["resellerContext"] = reseller_context
    return _call("GetSubscription", body)


@mcp.tool()
def also_get_subscriptions(parent_account_id: int, reseller_context: int | None = None) -> Any:
    """List all subscriptions under a parent/customer account."""
    body: dict[str, Any] = {"parentAccountId": parent_account_id}
    if reseller_context is not None:
        body["resellerContext"] = reseller_context
    return _call("GetSubscriptions", body)


@mcp.tool()
def also_create_subscription(
    parent_account_id: int,
    service_name: str,
    fields: dict[str, Any],
    contract_id: str | None = None,
    confirm: bool = False,
) -> Any:
    """
    Book a new subscription. service_name is the ProductName from
    also_get_possible_services; fields must satisfy what
    also_get_fields_for_service returned (validate first with also_validate_fields).

    This creates a billable subscription. Requires confirm=true.
    """
    if (err := _require_confirm(confirm, "creating a subscription")) is not None:
        return err
    subscription_account: dict[str, Any] = {
        "ParentAccountId": parent_account_id,
        "ServiceName": service_name,
        "Fields": fields,
    }
    if contract_id is not None:
        subscription_account["ContractId"] = contract_id
    return _call("CreateSubscription", {"subscriptionAccount": subscription_account})


@mcp.tool()
def also_update_subscription(
    account_id: int,
    service_name: str,
    parent_account_id: int,
    fields: dict[str, Any],
    contract_id: str | None = None,
    confirm: bool = False,
) -> Any:
    """Update an existing subscription's fields. Requires confirm=true."""
    if (err := _require_confirm(confirm, "updating a subscription")) is not None:
        return err
    subscription_account: dict[str, Any] = {
        "AccountId": account_id,
        "ServiceName": service_name,
        "ParentAccountId": parent_account_id,
        "Fields": fields,
    }
    if contract_id is not None:
        subscription_account["ContractId"] = contract_id
    return _call("UpdateSubscription", {"subscriptionAccount": subscription_account})


@mcp.tool()
def also_get_subscription_fields_for_upgrade(account_id: int, target_product_name: str) -> Any:
    """Get the fields required to upgrade a subscription to target_product_name."""
    return _call(
        "GetSubscriptionFieldsForUpgrade",
        {"accountId": account_id, "targetProductName": target_product_name},
    )


@mcp.tool()
def also_execute_subscription_upgrade(
    source_account_id: int,
    target_product_name: str,
    field_values: dict[str, Any],
    target_account_id: int | None = None,
    confirm: bool = False,
) -> Any:
    """Upgrade a subscription to a different product. Requires confirm=true."""
    if (err := _require_confirm(confirm, "executing a subscription upgrade")) is not None:
        return err
    body: dict[str, Any] = {
        "sourceAccountId": source_account_id,
        "targetProductName": target_product_name,
        "fieldValues": field_values,
    }
    if target_account_id is not None:
        body["targetAccountId"] = target_account_id
    return _call("ExecuteSubscriptionUpgrade", body)


@mcp.tool()
def also_terminate_account(account_id: int, termination_reason: str | None = None, confirm: bool = False) -> Any:
    """Terminate (cancel) a subscription/account. This is irreversible. Requires confirm=true."""
    if (err := _require_confirm(confirm, "terminating an account/subscription")) is not None:
        return err
    body: dict[str, Any] = {"accountId": account_id}
    if termination_reason is not None:
        body["terminationReason"] = termination_reason
    return _call("TerminateAccount", body)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


@mcp.tool()
def also_get_latest_invoices(reseller_context: int | None = None) -> Any:
    """Get the most recent invoices."""
    body: dict[str, Any] = {}
    if reseller_context is not None:
        body["resellerContext"] = reseller_context
    return _call("GetLatestInvoices", body)


@mcp.tool()
def also_get_latest_invoices_for_period(year: int, month: int, reseller_context: int | None = None) -> Any:
    """Get invoices for a specific year/month."""
    body: dict[str, Any] = {"year": year, "month": month}
    if reseller_context is not None:
        body["resellerContext"] = reseller_context
    return _call("GetLatestInvoicesForPeriod", body)


# ---------------------------------------------------------------------------
# Escape hatch for endpoints not explicitly wrapped above
# ---------------------------------------------------------------------------


@mcp.tool()
def also_raw_call(endpoint: str, body: dict[str, Any] | None = None, confirm: bool = False) -> Any:
    """
    Call any Marketplace SimpleAPI endpoint directly by name (e.g. "GetCreditLimit",
    "SetSpecialDeal", "GetReports"), passing body as the raw JSON request payload.

    Use this for endpoints not covered by a dedicated tool. Check the field names
    against the Swagger spec (MarketplaceSimpleAPI on SwaggerHub) first - they are
    not validated here. Always requires confirm=true, since this can call any
    endpoint including destructive ones.
    """
    if (err := _require_confirm(confirm, f"calling raw endpoint '{endpoint}'")) is not None:
        return err
    return _call(endpoint, body or {})


# ---------------------------------------------------------------------------
# HTTP transport (Cloud/Docker) with bearer auth
# ---------------------------------------------------------------------------


def _build_http_app():
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import JSONResponse

    # transport_security: DNS-rebinding protection disabled, same as
    # plesk-mcp/bexio-mcp - otherwise the SDK blocks every request whose Host
    # header isn't "localhost"/an IP with a 421 "Invalid Host header", even
    # though the server is deliberately reachable through a reverse proxy
    # under a real domain. Actual access control is MCP_API_KEY /
    # _BearerAuthMiddleware below.
    # json_response=True: plain application/json responses instead of an SSE
    # stream - more robust behind reverse proxies (see bexio-mcp).
    starlette_app = mcp.streamable_http_app(
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        host=_HTTP_HOST,
    )

    class _BearerAuthMiddleware:
        """Minimal ASGI middleware: checks 'Authorization: Bearer <token>'."""

        def __init__(self, app, token: str):
            self.app = app
            self.token = token

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode("latin-1")
            if auth_header != f"Bearer {self.token}":
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
            await self.app(scope, receive, send)

    secured_app = _BearerAuthMiddleware(starlette_app, _MCP_API_KEY)
    # CORS wraps around the auth middleware: browser-based MCP clients (e.g.
    # claude.ai) call the endpoint via cross-origin JS fetch. Preflight
    # OPTIONS requests (no Authorization header) are answered directly by
    # CORSMiddleware, before they reach the bearer check.
    return CORSMiddleware(
        secured_app,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id"],
    )


async def _run_http_server() -> None:
    import uvicorn

    app = _build_http_app()
    config = uvicorn.Config(app, host=_HTTP_HOST, port=_HTTP_PORT, log_level="info")
    srv = uvicorn.Server(config)
    print(f"also-marketplace-mcp HTTP server running on {_HTTP_HOST}:{_HTTP_PORT}", flush=True)
    await srv.serve()


def main() -> None:
    if _HTTP_MODE:
        import asyncio

        asyncio.run(_run_http_server())
    else:
        mcp.run(transport="stdio")


def run_server() -> None:
    main()


if __name__ == "__main__":
    main()
