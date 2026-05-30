"""Authentication module — validates Microsoft Entra ID access tokens.

Strategy: We call Microsoft Graph's `/me` endpoint with the bearer token.
If Graph returns 200, the token is valid and we extract the user's OID
(object ID) and display name / email. This avoids pulling in a full JWT
validation library (python-jose, cryptography, JWKS fetching) while
remaining correct for both personal and work/school accounts.

The result is cached per-token for the lifetime of the request so repeated
calls to `get_current_user` in the same request don't hit Graph twice.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException, Request, status

log = logging.getLogger(__name__)

GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me"
GRAPH_TIMEOUT = 10.0


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """Authenticated user extracted from the MS access token."""

    # The `id` field from Graph /me — this is the user's Object ID (OID),
    # a stable GUID that never changes for the account.
    user_id: str
    # Display name (e.g. "John Doe") — may be empty for personal accounts.
    display_name: str
    # Email / UPN — used for display only, not as a key.
    email: str


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(maxsplit=1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


async def _validate_token_via_graph(token: str) -> CurrentUser:
    """Call Graph /me and extract user info. Raises HTTPException on failure."""
    try:
        async with httpx.AsyncClient(timeout=GRAPH_TIMEOUT) as client:
            resp = await client.get(
                GRAPH_ME_URL,
                headers={"Authorization": f"Bearer {token}"},
            )
    except (httpx.HTTPError, OSError) as exc:
        log.warning("Network error validating token via Graph: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not reach Microsoft Graph to validate token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if resp.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if resp.status_code != 200:
        log.warning("Graph /me returned %s: %s", resp.status_code, resp.text[:200])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate access token with Microsoft Graph.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    data = resp.json()
    user_id = data.get("id", "")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is valid but Graph returned no user ID.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    display_name = data.get("displayName") or ""
    email = (
        data.get("mail")
        or data.get("userPrincipalName")
        or data.get("preferredLanguage")
        or ""
    )

    return CurrentUser(user_id=user_id, display_name=display_name, email=email)


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """FastAPI dependency: extract and validate the current user from the token.

    The validated user is cached on `request.state` so multiple dependencies
    in the same request don't re-validate.
    """
    # Check cache first
    cached: CurrentUser | None = getattr(request.state, "current_user", None)
    if cached is not None:
        return cached

    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header with Bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await _validate_token_via_graph(token)
    request.state.current_user = user
    return user


async def get_optional_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> CurrentUser | None:
    """Like get_current_user but returns None instead of 401 when no token."""
    token = _extract_bearer(authorization)
    if not token:
        return None

    cached: CurrentUser | None = getattr(request.state, "current_user", None)
    if cached is not None:
        return cached

    try:
        user = await _validate_token_via_graph(token)
        request.state.current_user = user
        return user
    except HTTPException:
        return None
