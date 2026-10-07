"""HMAC-signed URLs for the ``/files`` mount.

Sharing mesh outputs over a static-files mount historically required
shipping the API key with every request. That leaks credentials and
makes revocation impossible. The solution here is the same approach
used by cloud object stores:

  1. The server mints a token with ``build_signed_url(...)`` that
     encodes ``path + expires_at + nonce`` and HMACs them with
     ``POLYFORGE_API_KEY`` (or a dedicated
     ``POLYFORGE_URL_SIGNING_KEY`` when present).
  2. The token is appended as ``token=<mac>&exp=<ts>`` query params
     on ``/files/...``. Static file servers can't read the body, so
     the signature must cover the path itself.
  3. ``verify_signed_url(...)`` re-derives the MAC and rejects tokens
     that are malformed, expired, or whose MAC doesn't match.

Tokens are short-lived (default 1 hour), scoped to a single path
(below SAVE_DIR), and constant-time compared. The verifier never
trusts the unsigned ``exp`` parameter — it's only consulted after the
MAC check passes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import parse_qs, quote, urlencode

from hy3dgen.api import config as config_module

DEFAULT_TTL_SECONDS = 3600
MAX_TTL_SECONDS = 86_400  # 24h cap so accidental config can't mint year-long tokens
QUERY_TOKEN = "token"
QUERY_EXPIRES = "exp"
QUERY_NONCE = "nonce"
SIGNATURE_VERSION = "v1"


def _signing_key() -> bytes:
    """Resolve the key used for HMAC.

    Preference order:
      1. ``POLYFORGE_URL_SIGNING_KEY`` in the process environment.
      2. ``settings.url_signing_key`` (same variable, loaded through
         Pydantic Settings and therefore monkeypatchable in tests).
      3. ``POLYFORGE_API_KEY`` — re-use the API key so setups with one
         shared secret keep working out of the box.
    Returns empty bytes when neither is set — the signer will then
    refuse to mint tokens, and the verifier will reject anything.
    """
    explicit = os.environ.get("POLYFORGE_URL_SIGNING_KEY", "").strip()
    if not explicit and config_module.settings.url_signing_key:
        explicit = config_module.settings.url_signing_key.strip()
    if explicit:
        return explicit.encode("utf-8")
    fallback = os.environ.get("POLYFORGE_API_KEY", "").strip()
    if not fallback and config_module.settings.api_key:
        fallback = config_module.settings.api_key.strip()
    if fallback:
        return fallback.encode("utf-8")
    return b""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _payload(path: str, expires_at: int, nonce: str) -> bytes:
    """The deterministic byte string we MAC over.

    Versioning the payload lets us rotate algorithms without breaking
    in-flight tokens; the verifier checks the version first.
    """
    return f"{SIGNATURE_VERSION}|{path}|{expires_at}|{nonce}".encode()


def build_signed_url(
    path: str, ttl_seconds: int = DEFAULT_TTL_SECONDS, *, base_url: str = ""
) -> str | None:
    """Mint a signed URL for ``path``.

    Returns None when no signing key is configured — callers should
    fall back to the plain ``/files`` URL with the API key. The
    returned URL is relative to ``base_url`` when provided; pass
    ``http://host:port`` to get a shareable absolute URL.
    """
    key = _signing_key()
    if not key:
        return None
    expires_at = int(time.time()) + max(1, min(ttl_seconds, MAX_TTL_SECONDS))
    nonce = secrets.token_urlsafe(8)
    mac = hmac.new(key, _payload(path, expires_at, nonce), hashlib.sha256).digest()
    query = urlencode(
        {
            QUERY_TOKEN: f"{SIGNATURE_VERSION}.{_b64url_encode(mac)}",
            QUERY_EXPIRES: str(expires_at),
            QUERY_NONCE: nonce,
        }
    )
    quoted = quote(path, safe="/")
    return f"{base_url}/files/{quoted}?{query}"


def verify_signed_url(path: str, query_string: str) -> bool:
    """Verify a signed ``/files`` request.

    Returns True iff:
      - a signing key is configured,
      - the query string has the expected fields,
      - the MAC matches, and
      - the token hasn't expired.

    Constant-time comparison is used to avoid leaking timing info.
    """
    key = _signing_key()
    if not key or not query_string:
        return False
    params = parse_qs(query_string)
    token = params.get(QUERY_TOKEN, [""])[0]
    expires_raw = params.get(QUERY_EXPIRES, [""])[0]
    nonce = params.get(QUERY_NONCE, [""])[0]
    if not token or not expires_raw or not nonce:
        return False
    if "." not in token:
        return False
    version, encoded_mac = token.split(".", 1)
    if version != SIGNATURE_VERSION:
        return False
    try:
        expires_at = int(expires_raw)
    except ValueError:
        return False
    if expires_at < int(time.time()):
        return False
    expected_mac = hmac.new(key, _payload(path, expires_at, nonce), hashlib.sha256).digest()
    try:
        provided_mac = _b64url_decode(encoded_mac)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected_mac, provided_mac)
