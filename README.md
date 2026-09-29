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
| `MCP_TRANSPORT` | no | `stdio` | Set to `http` for the Docker/Portainer deployment |
| `MCP_API_KEY` | **yes, when `MCP_TRANSPORT=http`** | - | Static bearer token. The server refuses to start in http mode without it. Every request must send `Authorization: Bearer <token>`. Generate with `openssl rand -hex 32`. |
| `MCP_HOST` | no | `0.0.0.0` | Bind address inside the container |
| `MCP_PORT` | no | `8000` | Port inside the container |
| `MCP_BIND_ADDR` | no | `127.0.0.1` | Host-side bind address (compose only) - public access goes through the reverse proxy, not a direct `0.0.0.0` bind |
| `MCP_HOST_PORT` | no | `8424` | Host-side port (compose only) |

Never commit real credentials. Set them as environment variables on the
container/stack (e.g. in Portainer), same as the other KDT MCP servers.

**Security:** `MCP_TRANSPORT=http` is meant to sit behind a reverse proxy
with TLS, same as zammad-mcp/plesk-mcp. Never run it with `MCP_TRANSPORT=http`
reachable from the internet without `MCP_API_KEY` set - there is no other
access control, and the exposed tools include booking and terminating
subscriptions.

## Running locally

```bash
pip install -e .
ALSO_API_USER=... ALSO_API_PASSWORD=... also-marketplace-mcp
```

This runs stdio mode (for a local Claude Desktop config entry), not the HTTP
server.

## Running with Docker

```bash
docker build -t also-marketplace-mcp .
docker run -p 127.0.0.1:8424:8000 \
  -e ALSO_API_USER=... \
  -e ALSO_API_PASSWORD=... \
  -e MCP_API_KEY=... \
  also-marketplace-mcp
```

The server then listens on streamable-HTTP at `http://127.0.0.1:8424/mcp`,
requiring the `Authorization: Bearer <MCP_API_KEY>` header on every request.

Deploy the same way as `zammad-mcp` / `plesk-mcp`: `docker-compose.yml`
builds the image and binds it to `127.0.0.1` by default; the existing
reverse proxy (nginx) in front of `*.kdt-solutions.ch` terminates TLS and
forwards to it. Run it as a Portainer stack with the environment variables
above set as secrets, and add it in Claude as a custom remote MCP connector
pointing at `https://also.kdt-solutions.ch/mcp` with the bearer token as
its auth header.

## Tools

Read-only:

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
  `GetReports`). Always requires `confirm=true`.

## Typical booking flow

1. `also_get_companies` — find the customer's account ID
2. `also_get_possible_services` — see which products can be booked for them
3. `also_get_fields_for_service` — get the required fields for a product
4. `also_validate_fields` — check values before committing
5. `also_create_subscription` with `confirm=true` — book it

## Errors

ALSO returns errors as XML (SOAP-style fault), regardless of `Accept`
headers. This client parses that and returns `{"error": "<message>"}` from
the tool instead of raising, so failures are visible to the model without
crashing the server.
