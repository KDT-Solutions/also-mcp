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
| `HOST` | no | `0.0.0.0` | Bind address |
| `PORT` | no | `8420` | Listen port |

Never commit real credentials. Set them as environment variables on the
container/stack (e.g. in Portainer), same as the other KDT MCP servers.

## Running locally

```bash
pip install -e .
ALSO_API_USER=... ALSO_API_PASSWORD=... also-marketplace-mcp
```

The server listens on streamable-HTTP at `http://<host>:<port>/mcp`.

## Running with Docker

```bash
docker build -t also-marketplace-mcp .
docker run -p 8420:8420 \
  -e ALSO_API_USER=... \
  -e ALSO_API_PASSWORD=... \
  also-marketplace-mcp
```

Deploy the same way as `zammad-mcp` / `plesk-mcp`: build via the included
GitHub Actions workflow (pushes to `ghcr.io/<org>/also-marketplace-mcp`),
then run it as a Portainer stack with the environment variables above set as
secrets, and add it in Claude as a custom remote MCP connector pointing at
`https://<your-host>/mcp`.

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
