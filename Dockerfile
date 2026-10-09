FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

# Build commit and version (set by GitHub Actions) - get_version returns both,
# so a redeploy can be checked for which build is actually running.
ARG GIT_SHA=unknown
ARG APP_VERSION=
ENV GIT_SHA=$GIT_SHA \
    APP_VERSION=$APP_VERSION

EXPOSE 8000

CMD ["also-marketplace-mcp"]
