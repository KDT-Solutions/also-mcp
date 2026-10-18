# Changelog

## 0.2

- Port mapping with a configurable bind address: `${MCP_BIND_ADDR:-127.0.0.1}:${MCP_HOST_PORT:-8424}:8000`. Until now the service listened on all interfaces including IPv6. **Before the first redeploy set `MCP_BIND_ADDR` in the stack to the Docker host IP the reverse proxy connects to**, otherwise the service is only reachable on `127.0.0.1`.
- New endpoint `GET /healthz` without auth, returns only `{"status": "ok"}`. It only checks that the process answers, not the ALSO API. All other paths still require the bearer token.
- `HEALTHCHECK` in the Dockerfile (Python/urllib on `/healthz`, interval 30s, timeout 5s, start_period 15s, retries 3).
- README: placeholders instead of real domains.
