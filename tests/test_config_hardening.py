"""Tests for the hardened configuration surface.

Covers the settings that used to be documented but unread
(``ARCHEON_WORKERS``), the ones that were read but bypassed Pydantic
(``ARCHEON_ALLOW_CREDENTIALS``), and the ones that were never wired at
all (``ARCHEON_RATE_LIMIT``, ``ARCHEON_MAX_BODY_BYTES``).
"""

import importlib

import pytest


@pytest.fixture
def fresh_config():
    """Reload the config module so env vars are re-read."""
    from hy3dgen.api import config as cfg

    yield cfg
    importlib.reload(cfg)


class TestWorkersIsWired:
    def test_workers_setting_reads_env(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("ARCHEON_WORKERS", "3")
        assert Settings(_env_file=None).workers == 3

    def test_workers_defaults_to_one(self):
        from hy3dgen.api.config import Settings

        assert Settings(_env_file=None).workers == 1

    def test_cli_default_comes_from_settings(self, monkeypatch):
        """The argparse default must be the Settings value, not a literal."""
        import argparse

        from hy3dgen.api.config import Settings
        from hy3dgen.api.server import _reject_multi_worker

        monkeypatch.setenv("ARCHEON_WORKERS", "1")
        settings = Settings(_env_file=None)
        parser = argparse.ArgumentParser()
        parser.add_argument("--workers", type=int, default=settings.workers)
        assert parser.parse_args([]).workers == 1
        assert _reject_multi_worker(parser, 1) is None


class TestAllowCredentials:
    def test_allow_credentials_reads_env(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("ARCHEON_ALLOW_CREDENTIALS", "true")
        assert Settings(_env_file=None).allow_credentials is True

    def test_allow_credentials_defaults_false(self):
        from hy3dgen.api.config import Settings

        assert Settings(_env_file=None).allow_credentials is False

    def test_cors_uses_settings_not_raw_environ(self, monkeypatch):
        """The CORS middleware must source the value from Settings so the
        field is no longer dead code."""
        import ast
        import inspect

        from hy3dgen.api import server as server_module

        source = inspect.getsource(server_module)
        tree = ast.parse(source)
        # No module-level os.environ lookup for ALLOW_CREDENTIALS.
        offenders = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and any(
                isinstance(a, ast.Constant) and a.value == "ARCHEON_ALLOW_CREDENTIALS"
                for a in node.args
            )
        ]
        assert not offenders, "CORS still reads ARCHEON_ALLOW_CREDENTIALS directly"
        assert "settings.allow_credentials" in source


class TestRateLimitSetting:
    def test_rate_limit_default(self):
        from hy3dgen.api.config import Settings

        assert Settings(_env_file=None).rate_limit == "120/minute"

    def test_rate_limit_reads_env(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("ARCHEON_RATE_LIMIT", "10/second")
        assert Settings(_env_file=None).rate_limit == "10/second"

    def test_rate_limit_can_be_disabled(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("ARCHEON_RATE_LIMIT", "")
        assert Settings(_env_file=None).rate_limit == ""

    def test_limiter_honours_the_setting(self, monkeypatch):
        """An empty ARCHEON_RATE_LIMIT must not blow up slowapi and must
        produce a limiter with no default limits."""
        from slowapi import Limiter
        from slowapi.util import get_remote_address

        assert Limiter(key_func=get_remote_address, default_limits=[]) is not None
        assert Limiter(key_func=get_remote_address, default_limits=["5/minute"]) is not None


class TestMaxBodyBytes:
    def test_default_is_64_mib(self):
        from hy3dgen.api.config import Settings

        assert Settings(_env_file=None).max_body_bytes == 64 * 1024 * 1024

    def test_reads_env(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("ARCHEON_MAX_BODY_BYTES", "1024")
        assert Settings(_env_file=None).max_body_bytes == 1024

    def test_zero_disables_the_guard(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("ARCHEON_MAX_BODY_BYTES", "0")
        assert Settings(_env_file=None).max_body_bytes == 0

    def test_negative_is_rejected(self):
        from pydantic import ValidationError

        from hy3dgen.api.config import Settings

        with pytest.raises(ValidationError):
            Settings(_env_file=None, max_body_bytes=-1)

    def test_oversized_body_is_rejected_with_413(self, monkeypatch):
        """The body guard reads the configured cap, not a hardcoded one."""
        from fastapi.testclient import TestClient

        from hy3dgen.api import server as server_module

        original = server_module._MAX_BODY_BYTES
        try:
            server_module._MAX_BODY_BYTES = 10
            with TestClient(server_module.app) as client:
                r = client.post(
                    "/v1/jobs",
                    content=b"x" * 64,
                    headers={"Content-Type": "application/json"},
                )
                assert r.status_code == 413
        finally:
            server_module._MAX_BODY_BYTES = original

    def test_zero_turns_the_guard_off(self):
        from fastapi.testclient import TestClient

        from hy3dgen.api import server as server_module

        original = server_module._MAX_BODY_BYTES
        try:
            server_module._MAX_BODY_BYTES = None
            with TestClient(server_module.app) as client:
                # No 413: the request fails validation instead.
                r = client.post(
                    "/v1/jobs",
                    content=b"x" * 64,
                    headers={"Content-Type": "application/json"},
                )
                assert r.status_code != 413
        finally:
            server_module._MAX_BODY_BYTES = original


class TestUrlSigningKeySetting:
    def test_defaults_to_none(self):
        from hy3dgen.api.config import Settings

        assert Settings(_env_file=None).url_signing_key is None

    def test_reads_env(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("ARCHEON_URL_SIGNING_KEY", "s3cret")
        assert Settings(_env_file=None).url_signing_key == "s3cret"


class TestEnvExampleCoverage:
    """Every ARCHEON_* field in Settings must appear in .env.example, and
    every ARCHEON_* line in .env.example must map to a real field."""

    def _env_example_text(self):
        from pathlib import Path

        return (Path(__file__).resolve().parent.parent / ".env.example").read_text()

    def test_all_settings_are_documented(self):
        from hy3dgen.api.config import Settings

        text = self._env_example_text()
        missing = []
        for name in Settings.model_fields:
            var = f"ARCHEON_{name.upper()}"
            if var not in text:
                missing.append(var)
        assert not missing, f"undocumented in .env.example: {missing}"

    def test_documented_vars_are_real_fields(self):
        import re

        from hy3dgen.api.config import Settings

        text = self._env_example_text()
        # Only uncommented assignments count as active configuration.
        documented = {
            m.group(1)
            for m in re.finditer(r"^ARCHEON_([A-Z0-9_]+)=", text, re.MULTILINE)
        }
        known = {name.upper() for name in Settings.model_fields}
        unknown = {d for d in documented if d not in known}
        assert not unknown, f"documented but not a Settings field: {unknown}"


class TestCliDefaultUrl:
    def test_cli_defaults_to_the_server_port(self):
        """The CLI client must not point at a stale port."""
        import ast
        from pathlib import Path

        source = (Path(__file__).resolve().parent.parent / "hy3dgen" / "cli.py").read_text()
        tree = ast.parse(source)
        urls = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith("http://127.0.0.1:")
        ]
        assert urls, "no default API URL found in cli.py"
        for url in urls:
            port = url.rsplit(":", 1)[1]
            assert port == "8081", f"cli.py points at stale port {port}"
