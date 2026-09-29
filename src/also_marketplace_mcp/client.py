"""
Thin HTTP client for the ALSO Cloud Marketplace SimpleAPI.

Reference: https://api.swaggerhub.com/apis/MarketplaceSimpleAPI/MarketplaceSimpleAPI/1.0.0

IMPORTANT: the exact field names/casing used here come from the public Swagger
spec and its examples. They have NOT been verified end-to-end against a live,
whitelisted ALSO account (authentication was still being provisioned by ALSO
support at the time this was written). If a call fails with an unexpected
"missing/invalid field" style error, check the raw error text returned by the
tool against the current spec, and adjust field names there.

Auth flow:
  1. POST {base_url}/GetSessionToken with {"username": ..., "password": ...}
  2. The response body is the session token (as a JSON string).
  3. Every subsequent call must carry header:
       Authenticate: CCPSessionId <token>
  4. MFA-enabled users cannot authenticate via this API - use a dedicated
     API user that ALSO has whitelisted for API access.

Errors are returned as XML (SOAP-style <Fault>) regardless of the
Accept header ALSO document this explicitly ("All returned errors are xml").
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://marketplace.also.ch/SimpleAPI/SimpleAPIService.svc/rest"


class AlsoApiError(RuntimeError):
    """Raised when the ALSO SimpleAPI returns a fault or an HTTP error."""

    def __init__(self, message: str, status_code: int | None = None, raw: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.raw = raw


def _parse_xml_fault(body: str) -> str:
    """Extract a human-readable message from ALSO's XML fault format."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return body.strip() or "Unknown error (unparseable XML fault)"

    # Namespaces vary; search by local tag name instead of full qualified name.
    def find_local(tag: str) -> str | None:
        for el in root.iter():
            local = el.tag.split("}")[-1]
            if local == tag and el.text:
                return el.text.strip()
        return None

    message = find_local("Message") or find_local("Text") or find_local("Reason")
    return message or body.strip()


class AlsoMarketplaceClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._token: str | None = None
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    # -- auth -----------------------------------------------------------

    def _login(self) -> str:
        resp = self._client.post(
            f"{self.base_url}/GetSessionToken",
            json={"username": self.username, "password": self.password},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            raise AlsoApiError(
                f"GetSessionToken failed: {_parse_xml_fault(resp.text)}",
                status_code=resp.status_code,
                raw=resp.text,
            )
        token = resp.text.strip()
        # Response is typically a JSON-encoded string ("abc123...").
        if token.startswith('"') and token.endswith('"'):
            try:
                token = json.loads(token)
            except json.JSONDecodeError:
                token = token.strip('"')
        if not token:
            raise AlsoApiError("GetSessionToken returned an empty token", raw=resp.text)
        self._token = token
        return token

    def _ensure_token(self) -> str:
        if not self._token:
            return self._login()
        return self._token

    # -- generic request --------------------------------------------------

    def call(self, endpoint: str, body: dict[str, Any] | None = None, retry_on_auth_error: bool = True) -> Any:
        """POST to a SimpleAPI endpoint (e.g. "GetCompany"), return parsed JSON (or raw text)."""
        token = self._ensure_token()
        resp = self._client.post(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            json=body or {},
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authenticate": f"CCPSessionId {token}",
            },
        )

        if resp.status_code == 401 or (resp.status_code >= 400 and "session" in resp.text.lower() and retry_on_auth_error):
            # Session likely expired - re-login once and retry.
            self._token = None
            self._login()
            return self.call(endpoint, body, retry_on_auth_error=False)

        content_type = resp.headers.get("content-type", "")
        if resp.status_code >= 400:
            raise AlsoApiError(
                f"{endpoint} failed ({resp.status_code}): {_parse_xml_fault(resp.text)}",
                status_code=resp.status_code,
                raw=resp.text,
            )

        if not resp.text.strip():
            return None

        if "xml" in content_type:
            # A 200 with an XML body would be unexpected, but handle it defensively.
            raise AlsoApiError(f"{endpoint} returned unexpected XML: {_parse_xml_fault(resp.text)}", raw=resp.text)

        try:
            return resp.json()
        except json.JSONDecodeError:
            return resp.text
