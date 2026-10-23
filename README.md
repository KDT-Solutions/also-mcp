# also-marketplace-mcp

MCP server for the [ALSO Cloud Marketplace SimpleAPI](https://api.swaggerhub.com/apis/MarketplaceSimpleAPI/MarketplaceSimpleAPI/1.0.0) — manage customers, users, subscriptions and invoices on the ALSO Cloud Marketplace programmatically instead of by hand in the portal.

> **Status note:** the field names/request shapes used here follow the public
> Swagger spec. They have not yet been verified end-to-end against a live
> account, because API access was still being provisioned by ALSO support
> (a dedicated non-MFA API user needs to be whitelisted by ALSO) when this was
> built. Verify each tool against a real response once your API access works,
> and adjust `src/also_marketplace_mcp/server.py` if a field name is off.

## Prerequisites

- An ALSO Marketplace API user (created by you in the Marketplace portal, then
  **whitelisted by ALSO support** — ALSO does not create this user for you).
  This user must not have MFA enabled; the SimpleAPI does not support MFA
  logins.

## Configuration

Environment variables (see `.env.example`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `ALSO_API_USER` | yes | - | API username, e.g. `api.user@yourdomain.ch` |
| `ALSO_API_PASSWORD` | yes | - | API password |
| `ALSO_BASE_URL` | no | `https://marketplace.also.ch/SimpleAPI/SimpleAPIService.svc/rest` | Marketplace SimpleAPI base URL for your region |
| `MCP_API_KEY` | **yes** | - | Static bearer token, at least 32 characters. The server refuses to start without it. Every request must send `Authorization: Bearer <token>`. Generate with `openssl rand -hex 32`. |
| `MCP_READONLY` | no | `false` | `true` disables every write tool (`also_create_*`, `also_update_subscription`, `also_execute_subscription_upgrade`, `also_terminate_account` and non-read `also_raw_call` endpoints), regardless of `confirm`. Read tools keep working. |
| `MCP_HOST` | no | `0.0.0.0` | Bind address inside the container |
| `MCP_PORT` | no | `8000` | Port inside the container |
| `MCP_HOST_PORT` | no | `8424` | Host-side port (compose only) |
| `MCP_BIND_ADDR` | no | `127.0.0.1` | Host-side bind address (compose only). Set it to the Docker host IP the reverse proxy connects to, e.g. `192.0.2.10` |

Never commit real credentials. Set them as environment variables on the
container/stack (e.g. in Portainer), same as the other KDT MCP servers.

**Security:** the server is meant to sit behind a reverse proxy with TLS,
same as zammad-mcp/plesk-mcp. `MCP_API_KEY` is mandatory - there is no other
access control, and the exposed tools include booking and terminating
subscriptions. The only path without the token is `GET /healthz` for the
Docker healthcheck; it returns just `{"status": "ok"}` (no version, no
configuration, no call to the ALSO API).

`confirm=true` on the write tools is a safety rail against accidental calls by
the model, not a security boundary - whoever holds `MCP_API_KEY` can set it.
For deployments that only need reads, set `MCP_READONLY=true`: every write
call is then refused server-side. Every write call (executed, failed or
refused) is written as one JSON line to stdout and therefore shows up in the
container logs (`docker logs` / Portainer): timestamp, tool, parameters
(password-like fields redacted) and outcome. The container runs as an
unprivileged user with a read-only root filesystem and no capabilities
(`docker-compose.yml`).

> **Important before the first redeploy with version 0.2:** the port mapping
> now binds to `127.0.0.1` by default. Set `MCP_BIND_ADDR` in the stack to the
> Docker host IP the reverse proxy connects to first - otherwise the service is
> only reachable on `127.0.0.1` and the proxy gets no connection.

## Running with Docker

```bash
docker build -t also-marketplace-mcp .
docker run -p 8424:8000 \
  -e ALSO_API_USER=... \
  -e ALSO_API_PASSWORD=... \
  -e MCP_API_KEY=... \
  also-marketplace-mcp
```

The server then listens on streamable-HTTP at `http://127.0.0.1:8424/mcp`,
requiring the `Authorization: Bearer <MCP_API_KEY>` header on every request
except `GET /healthz`.

Deploy the same way as `zammad-mcp` / `plesk-mcp`: GitHub Actions builds the
image on every push to `main` and publishes it as
`ghcr.io/kdt-solutions/also-marketplace-mcp` (tags `latest`, the commit SHA and
the version). `docker-compose.yml` uses that image with `pull_policy: always`,
so "Pull and redeploy" in Portainer always fetches the current build. The
port is published on `MCP_BIND_ADDR:MCP_HOST_PORT` (default `127.0.0.1:8424`);
access is only meant through the reverse proxy with TLS, which connects to
that address. Run it as a Portainer stack with the environment variables
above set as secrets (including `MCP_BIND_ADDR`, e.g. `192.0.2.10`), and add it
in Claude as a custom remote MCP connector pointing at
`https://mcp.example.com/mcp` with the bearer token as its auth header.

## Tools

Read-only:

- `get_version` — version and build commit of the running server (to verify a redeploy)
- `also_get_company`, `also_get_companies`, `also_get_company_by_vat_id`
- `also_get_users`
- `also_get_possible_services`, `also_get_fields_for_service`, `also_validate_fields`
- `also_get_subscription`, `also_get_subscriptions`
- `also_get_subscription_fields_for_upgrade`
- `also_get_latest_invoices`, `also_get_latest_invoices_for_period`

Write (all require `confirm=true`):

- `also_create_company`, `also_create_user`
- `also_create_subscription`, `also_update_subscription`
- `also_execute_subscription_upgrade`
- `also_terminate_account`
- `also_raw_call` — generic escape hatch for any SimpleAPI endpoint not
  explicitly wrapped above (e.g. `GetCreditLimit`, `SetSpecialDeal`,
  `GetReports`). The endpoint must be a plain method name (letters and
  digits). Endpoints starting with `Get`, `List` or `Validate` are treated as
  reads and run without `confirm`; everything else is a write: it requires
  `confirm=true`, is blocked under `MCP_READONLY` and is audit-logged.

## Account IDs: AccountId vs. NumericId

ALSO gives every account two numbers:

- **AccountId** — the internal ID the SimpleAPI works with (field `AccountId`
  in `GetCompany` / `GetCompanies` responses).
- **NumericId** — the number shown in the Marketplace portal (field `NumericId`).

Every `account_id` / `parent_account_id` parameter expects the **AccountId**.
Passing a NumericId does not raise an error — the API just returns an empty
result, which is easy to misread as "no data".

To make this hard to get wrong, the server resolves parent IDs itself:

- `also_get_companies` and `also_get_subscriptions` default to your own
  account when `parent_account_id` is omitted.
- If your own NumericId is passed anywhere, it is mapped to your own AccountId
  (looked up once via `GetCompany` and cached).
- Customer IDs are passed through unchanged — take them from the `AccountId`
  field of `also_get_companies`, not from the portal.

## Typical booking flow

1. `also_get_companies` — find the customer's `AccountId` (not the NumericId)
2. `also_get_possible_services` — see which products can be booked for them
3. `also_get_fields_for_service` — get the required fields for a product
4. `also_validate_fields` — check values before committing
5. `also_create_subscription` with `confirm=true` — book it

## Versioning

The version is `<major.minor>.<patch>`: `major.minor` comes from `pyproject.toml`,
the patch part is the number of commits that changed `src/`, `pyproject.toml`,
the `Dockerfile` or the workflow, so it increases automatically with every code
change. GitHub Actions bakes the version and the commit SHA into the image;
`get_version` returns both. After a redeploy, compare the commit with the latest
commit on `main`.

## Errors

ALSO returns errors as XML (SOAP-style fault), regardless of `Accept`
headers. This client parses that (with `defusedxml`, bodies over 64 KB are
not parsed) and returns `{"error": "<message>"}` from the tool instead of
raising, so failures are visible to the model without crashing the server.
Connection problems (timeouts, DNS, TLS) are reported the same way with the
error type only, without the URL.

## Tests

```bash
pip install -e ".[test]"
pytest -q
```

Covers the bearer auth and `/healthz`, the write guard (`confirm`,
`MCP_READONLY`), the `also_raw_call` allowlist and endpoint validation, the
audit log (including redaction) and the client error handling, all without
calling ALSO.
