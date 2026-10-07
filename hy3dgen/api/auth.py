"""API key authentication for the PolyForge backend.

When ``POLYFORGE_API_KEY`` is set, every request to a protected route
must include a matching ``X-API-Key`` header. When the env var is
unset, auth is disabled and the server is intended to be bound to
``127.0.0.1`` only.

The check is implemented as a FastAPI dependency so routes can opt in
explicitly (``/health`` stays open for unauthenticated monitoring), and
tests can override it via ``app.dependency_overrides``.
"""

from __future__ import annotations

import hmac
import os
from typing import Annotated

from dotenv import dotenv_values
from fastapi import Depends, Header, HTTPException, status

from hy3dgen.api import config as config_module


def get_api_key() -> str | None:
    """Read the configured API key.

    ``Settings`` is the canonical source, but the process environment is
    checked first so key rotation does not require reimporting this module.
    Returns None when auth is disabled (no key configured). Callers should
    treat None as "skip auth" rather than "deny".
    """
    configured = os.environ.get("POLYFORGE_API_KEY")
    if configured is None:
        configured = config_module.settings.api_key
    if configured is None:
        try:
            configured = dotenv_values(".env").get("POLYFORGE_API_KEY")
        except Exception:
            configured = None
    key = (configured or "").strip()
    return key or None


async def require_api_key(
    provided: Annotated[str | None, Header(alias="X-API-Key")] = None,
    expected: Annotated[str | None, Depends(get_api_key)] = None,
) -> None:
    """FastAPI dependency that enforces X-API-Key.

    - If no key is configured (``expected is None``), the request is allowed.
    - If a key is configured but the client did not send one, 401.
    - If a key is configured and the client sent one, it must match exactly
      (constant-time comparison to avoid leaking length information).
    """
    if expected is None:
        return
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )
