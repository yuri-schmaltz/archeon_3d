"""Tests for the signed-URL feature.

Covers:
  - build_signed_url returns None when no key is configured
  - tokens are deterministic in format (versioned, base64-url)
  - verify_signed_url accepts a freshly-minted token for the right path
  - verify_signed_url rejects different paths, expired tokens, and
    tampered MACs
  - the TTL is bounded by MAX_TTL_SECONDS
"""

from __future__ import annotations

import time

import pytest

from hy3dgen.api import signed_urls


@pytest.fixture(autouse=True)
def reset_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip both signing-key env vars between tests so we get a known state."""
    monkeypatch.delenv("ARCHEON_URL_SIGNING_KEY", raising=False)
    monkeypatch.delenv("ARCHEON_API_KEY", raising=False)


def test_no_key_returns_none() -> None:
    assert signed_urls.build_signed_url("abc.glb") is None
    assert signed_urls.verify_signed_url("abc.glb", "token=v1.x&exp=9999999999&nonce=n") is False


def test_round_trip_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHEON_API_KEY", "secret-key")
    url = signed_urls.build_signed_url("abc.glb", ttl_seconds=60)
    assert url is not None
    assert url.startswith("/files/abc.glb?")
    qs = url.split("?", 1)[1]
    assert signed_urls.verify_signed_url("abc.glb", qs) is True


def test_dedicated_signing_key_preferred(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHEON_API_KEY", "api-key")
    monkeypatch.setenv("ARCHEON_URL_SIGNING_KEY", "url-key")
    # Token minted with URL_SIGNING_KEY must NOT verify under the API key alone.
    url = signed_urls.build_signed_url("abc.glb", ttl_seconds=60)
    assert url is not None
    qs = url.split("?", 1)[1]
    monkeypatch.delenv("ARCHEON_URL_SIGNING_KEY")
    assert signed_urls.verify_signed_url("abc.glb", qs) is False
    monkeypatch.setenv("ARCHEON_URL_SIGNING_KEY", "url-key")
    assert signed_urls.verify_signed_url("abc.glb", qs) is True


def test_path_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHEON_API_KEY", "secret-key")
    url = signed_urls.build_signed_url("abc.glb", ttl_seconds=60)
    qs = url.split("?", 1)[1]
    # Same token must NOT work for a different file
    assert signed_urls.verify_signed_url("xyz.glb", qs) is False


def test_expired_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHEON_API_KEY", "secret-key")
    # Mint with a tiny TTL, then jump the clock past the expiry.
    now = int(time.time())
    monkeypatch.setattr(signed_urls.time, "time", lambda: now)
    url = signed_urls.build_signed_url("abc.glb", ttl_seconds=1)
    qs = url.split("?", 1)[1]
    # Advance the clock by 5s — token must now be expired.
    monkeypatch.setattr(signed_urls.time, "time", lambda: now + 5)
    assert signed_urls.verify_signed_url("abc.glb", qs) is False


def test_tampered_mac_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHEON_API_KEY", "secret-key")
    url = signed_urls.build_signed_url("abc.glb", ttl_seconds=60)
    # Flip a character in the MAC payload.
    prefix, _token, rest = url.split("?", 1)[1].partition("&")
    key, _, value = prefix.partition("=")
    head, _dot, tail = value.partition(".")
    mutated = head + "." + ("A" if not tail.startswith("A") else "B") + tail[1:]
    tampered = f"{key}={mutated}&{rest}"
    assert signed_urls.verify_signed_url("abc.glb", tampered) is False


def test_malformed_query_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHEON_API_KEY", "secret-key")
    assert signed_urls.verify_signed_url("abc.glb", "") is False
    assert signed_urls.verify_signed_url("abc.glb", "foo=bar") is False
    assert signed_urls.verify_signed_url("abc.glb", "token=v1.x&exp=notanumber") is False


def test_ttl_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHEON_API_KEY", "secret-key")
    url = signed_urls.build_signed_url("abc.glb", ttl_seconds=10**9)
    qs = url.split("?", 1)[1]
    # Even though we asked for a millennium, the cap kicks in.
    # Verify should still pass (cap doesn't make the token invalid)
    assert signed_urls.verify_signed_url("abc.glb", qs) is True
    # The expires param should be at most now + MAX_TTL_SECONDS + slack.
    from urllib.parse import parse_qs

    params = parse_qs(qs)
    exp = int(params[signed_urls.QUERY_EXPIRES][0])
    upper = int(time.time()) + signed_urls.MAX_TTL_SECONDS + 1
    assert exp <= upper
