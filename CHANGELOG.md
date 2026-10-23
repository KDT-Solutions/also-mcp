# Changelog

## 0.3

- `also_raw_call`: endpoints starting with `Get`, `List` or `Validate` are reads and run without `confirm`; every other endpoint is a write and requires `confirm=true`. The endpoint must be a plain method name (letters/digits, no path, scheme or host).
- New `MCP_READONLY=true`: refuses every write tool (`also_create_company`, `also_create_user`, `also_create_subscription`, `also_update_subscription`, `also_execute_subscription_upgrade`, `also_terminate_account`, non-read `also_raw_call`) server-side, regardless of `confirm`. Default `false`.
- Audit log: every write call (executed, failed or refused) is one JSON line on stdout with timestamp, tool, parameters (password-like fields redacted) and outcome.
- `MCP_API_KEY` is compared in constant time and must be at least 32 characters (startup check).
- XML fault parsing with `defusedxml` (new dependency), bodies over 64 KB are not parsed; httpx connection errors are returned as `{"error": ...}` with the error type only, without URL.
- Dockerfile runs as unprivileged user (uid 10001); compose with `read_only`, `cap_drop: ALL`, `no-new-privileges`; dependencies pinned exactly, `mcp` without the `cli` extra.
- Tests for the write guard, raw-call allowlist/validation, audit log and client error handling.

## 0.2

- Port mapping with a configurable bind address: `${MCP_BIND_ADDR:-127.0.0.1}:${MCP_HOST_PORT:-8424}:8000`. Until now the service listened on all interfaces including IPv6. **Before the first redeploy set `MCP_BIND_ADDR` in the stack to the Docker host IP the reverse proxy connects to**, otherwise the service is only reachable on `127.0.0.1`.
- New endpoint `GET /healthz` without auth, returns only `{"status": "ok"}`. It only checks that the process answers, not the ALSO API. All other paths still require the bearer token.
- `HEALTHCHECK` in the Dockerfile (Python/urllib on `/healthz`, interval 30s, timeout 5s, start_period 15s, retries 3).
- README: placeholders instead of real domains.
