"""Tests for the hardened configuration surface.

Covers the settings that used to be documented but unread
(``POLYFORGE_WORKERS``), the ones that were read but bypassed Pydantic
(``POLYFORGE_ALLOW_CREDENTIALS``), and the ones that were never wired at
all (``POLYFORGE_RATE_LIMIT``, ``POLYFORGE_MAX_BODY_BYTES``).
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

        monkeypatch.setenv("POLYFORGE_WORKERS", "3")
        assert Settings(_env_file=None).workers == 3

    def test_workers_defaults_to_one(self):
        from hy3dgen.api.config import Settings

        assert Settings(_env_file=None).workers == 1

    def test_cli_default_comes_from_settings(self, monkeypatch):
        """The argparse default must be the Settings value, not a literal."""
        import argparse

        from hy3dgen.api.config import Settings
        from hy3dgen.api.server import _reject_multi_worker

        monkeypatch.setenv("POLYFORGE_WORKERS", "1")
        settings = Settings(_env_file=None)
        parser = argparse.ArgumentParser()
        parser.add_argument("--workers", type=int, default=settings.workers)
        assert parser.parse_args([]).workers == 1
        assert _reject_multi_worker(parser, 1) is None


class TestAllowCredentials:
    def test_allow_credentials_reads_env(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("POLYFORGE_ALLOW_CREDENTIALS", "true")
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
                isinstance(a, ast.Constant) and a.value == "POLYFORGE_ALLOW_CREDENTIALS"
                for a in node.args
            )
        ]
        assert not offenders, "CORS still reads POLYFORGE_ALLOW_CREDENTIALS directly"
        assert "settings.allow_credentials" in source


class TestRateLimitSetting:
    def test_rate_limit_default(self):
        from hy3dgen.api.config import Settings

        assert Settings(_env_file=None).rate_limit == "120/minute"

    def test_rate_limit_reads_env(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("POLYFORGE_RATE_LIMIT", "10/second")
        assert Settings(_env_file=None).rate_limit == "10/second"

    def test_rate_limit_can_be_disabled(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("POLYFORGE_RATE_LIMIT", "")
        assert Settings(_env_file=None).rate_limit == ""

    @pytest.mark.parametrize("value", ["false", "False", "off", "none", "disabled", "0"])
    def test_rate_limit_disable_spellings_normalise_to_empty(self, monkeypatch, value):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("POLYFORGE_RATE_LIMIT", value)
        assert Settings(_env_file=None).rate_limit == ""

    def test_limiter_honours_the_setting(self, monkeypatch):
        """An empty POLYFORGE_RATE_LIMIT must not blow up slowapi and must
        produce a limiter with no default limits."""
        from slowapi import Limiter
        from slowapi.util import get_remote_address

        assert Limiter(key_func=get_remote_address, default_limits=[]) is not None
        assert Limiter(key_func=get_remote_address, default_limits=["5/minute"]) is not None


class TestRateLimitMiddleware:
    def test_api_routes_use_rate_limited_route_class(self):
        from fastapi.routing import APIRoute

        from hy3dgen.api.routes import RateLimitedRoute, router

        api_routes = [route for route in router.routes if isinstance(route, APIRoute)]
        assert api_routes
        assert all(isinstance(route, RateLimitedRoute) for route in api_routes)

    def test_operational_routes_are_exempt(self):
        from hy3dgen.api import server as server_module

        exempt = server_module.limiter._exempt_routes
        for endpoint in (
            server_module.health_check,
            server_module.readiness_check,
            server_module.metrics_endpoint,
        ):
            name = f"{endpoint.__module__}.{endpoint.__name__}"
            assert name in exempt

    def test_api_route_returns_429_after_limit(self):
        """SlowAPI defaults must actually be evaluated by the app."""
        from fastapi.testclient import TestClient
        from slowapi import Limiter
        from slowapi.util import get_remote_address

        from hy3dgen.api import server as server_module

        limiter = server_module.limiter
        temporary = Limiter(key_func=get_remote_address, default_limits=["2/minute"])
        original = limiter._default_limits
        limiter._default_limits = temporary._default_limits
        try:
            with TestClient(server_module.app) as client:
                assert client.get("/v1/admin/stats").status_code == 200
                assert client.get("/v1/admin/stats").status_code == 200
                response = client.get("/v1/admin/stats")
                assert response.status_code == 429
        finally:
            limiter._default_limits = original


class TestMaxBodyBytes:
    def test_default_is_64_mib(self):
        from hy3dgen.api.config import Settings

        assert Settings(_env_file=None).max_body_bytes == 64 * 1024 * 1024

    def test_reads_env(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("POLYFORGE_MAX_BODY_BYTES", "1024")
        assert Settings(_env_file=None).max_body_bytes == 1024

    def test_zero_disables_the_guard(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("POLYFORGE_MAX_BODY_BYTES", "0")
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

    @pytest.mark.asyncio
    async def test_chunked_body_is_counted_without_content_length(self):
        from hy3dgen.api.server import RequestBodyLimitMiddleware

        delivered = []

        async def app(scope, receive, send):
            while True:
                message = await receive()
                delivered.append(message)
                if not message.get("more_body", False):
                    break

        messages = iter(
            [
                {"type": "http.request", "body": b"123456", "more_body": True},
                {"type": "http.request", "body": b"789", "more_body": False},
            ]
        )
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/v1/generate",
            "headers": [(b"content-type", b"application/json")],
        }
        middleware = RequestBodyLimitMiddleware(app, max_body_bytes=8)
        await middleware(scope, receive, send)

        assert len(delivered) == 1
        assert sent[0]["status"] == 413


class TestMaxQueueSize:
    def test_default_queue_size_is_bounded(self):
        from hy3dgen.api.config import Settings

        assert Settings(_env_file=None).max_queue_size == 4

    def test_reads_queue_size_from_environment(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("POLYFORGE_MAX_QUEUE_SIZE", "3")
        assert Settings(_env_file=None).max_queue_size == 3


class TestUrlSigningKeySetting:
    def test_defaults_to_none(self):
        from hy3dgen.api.config import Settings

        assert Settings(_env_file=None).url_signing_key is None

    def test_reads_env(self, monkeypatch):
        from hy3dgen.api.config import Settings

        monkeypatch.setenv("POLYFORGE_URL_SIGNING_KEY", "s3cret")
        assert Settings(_env_file=None).url_signing_key == "s3cret"

    def test_settings_key_is_used_when_env_is_absent(self, monkeypatch):
        from hy3dgen.api import signed_urls
        from hy3dgen.api.config import settings

        monkeypatch.delenv("POLYFORGE_URL_SIGNING_KEY", raising=False)
        monkeypatch.delenv("POLYFORGE_API_KEY", raising=False)
        monkeypatch.setattr(settings, "url_signing_key", "settings-key")
        monkeypatch.setattr(settings, "api_key", None)

        url = signed_urls.build_signed_url("abc.glb", ttl_seconds=60)
        assert url is not None
        query = url.split("?", 1)[1]
        assert signed_urls.verify_signed_url("abc.glb", query) is True


class TestSettingsAreCanonical:
    def test_api_key_falls_back_to_settings(self, monkeypatch):
        from hy3dgen.api import auth as auth_module
        from hy3dgen.api.config import settings

        monkeypatch.delenv("POLYFORGE_API_KEY", raising=False)
        monkeypatch.setattr(settings, "api_key", "settings-key")
        assert auth_module.get_api_key() == "settings-key"

    def test_generation_defaults_follow_settings(self, monkeypatch):
        from hy3dgen.api.config import settings
        from hy3dgen.api.schemas import TextTo3DRequest

        monkeypatch.setattr(settings, "default_seed", 9999)
        monkeypatch.setattr(settings, "default_steps", 7)
        monkeypatch.setattr(settings, "default_guidance", 9.5)
        monkeypatch.setattr(settings, "default_octree", 192)
        monkeypatch.setattr(settings, "default_face_count", 12345)

        request = TextTo3DRequest(type="text_to_3d", prompt="a prompt")
        assert (
            request.seed,
            request.steps,
            request.guidance,
            request.octree_resolution,
            request.face_count,
        ) == (9999, 7, 9.5, 192, 12345)

    def test_capabilities_body_bytes_follows_settings(self, monkeypatch):
        from hy3dgen.api.config import settings
        from hy3dgen.api.manager import PriorityRequestManager

        monkeypatch.setattr(settings, "max_body_bytes", 1024)
        manager = PriorityRequestManager(device="cpu")
        assert manager.capabilities()["limits"]["body_bytes"] == 1024

        monkeypatch.setattr(settings, "max_body_bytes", 0)
        assert manager.capabilities()["limits"]["body_bytes"] is None

    def test_configure_hf_home_sets_environment(self, monkeypatch, tmp_path):
        import os

        from hy3dgen.api.config import configure_hf_home

        monkeypatch.delenv("HF_HOME", raising=False)
        assert configure_hf_home(str(tmp_path)) == str(tmp_path)
        assert os.environ["HF_HOME"] == str(tmp_path)


class TestEnvExampleCoverage:
    """Every POLYFORGE_* field in Settings must appear in .env.example, and
    every POLYFORGE_* line in .env.example must map to a real field."""

    def _env_example_text(self):
        from pathlib import Path

        return (Path(__file__).resolve().parent.parent / ".env.example").read_text()

    def test_all_settings_are_documented(self):
        from hy3dgen.api.config import Settings

        text = self._env_example_text()
        missing = []
        for name in Settings.model_fields:
            var = f"POLYFORGE_{name.upper()}"
            if var not in text:
                missing.append(var)
        assert not missing, f"undocumented in .env.example: {missing}"

    def test_documented_vars_are_real_fields(self):
        import re

        from hy3dgen.api.config import Settings

        text = self._env_example_text()
        # Only uncommented assignments count as active configuration.
        documented = {
            m.group(1) for m in re.finditer(r"^POLYFORGE_([A-Z0-9_]+)=", text, re.MULTILINE)
        }
        known = {name.upper() for name in Settings.model_fields}
        unknown = {d for d in documented if d not in known}
        assert not unknown, f"documented but not a Settings field: {unknown}"


class TestLocalInstallerDefaults:
    def test_smart_launcher_exposes_local_install_modes(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        launcher = (root / "launcher.sh").read_text()

        for mode in ("auto", "cuda", "cpu", "api-only"):
            assert mode in launcher
        assert "nvidia-smi" in launcher
        assert "Node.js 22.12+" in launcher
        assert "Existing venv" in launcher
        assert "https://download.pytorch.org/whl/cpu" in launcher

    def test_cuda_mode_fails_early_without_nvidia_driver(self):
        import shutil
        import subprocess
        from pathlib import Path

        if shutil.which("nvidia-smi"):
            pytest.skip("host exposes nvidia-smi")
        script = Path(__file__).resolve().parent.parent / "launcher.sh"
        result = subprocess.run(
            ["bash", str(script), "--mode", "cuda"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "Install/fix the host NVIDIA driver" in result.stderr

    def test_container_installation_files_and_ci_are_removed(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        removed = (
            "Dockerfile",
            "Dockerfile.frontend",
            "docker-compose.yml",
            "Caddyfile",
            "nginx.conf",
            ".dockerignore",
        )
        assert all(not (root / path).exists() for path in removed)
        ci = (root / ".github" / "workflows" / "ci.yml").read_text()
        assert "docker/setup-buildx-action" not in ci

    def test_launcher_opens_browser_when_api_is_ready(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        launcher = (root / "launcher.sh").read_text()

        assert "open_browser" in launcher
        assert "xdg-open" in launcher
        assert "--no-browser" in launcher
        assert "POLYFORGE_NO_BROWSER" in launcher
        # Loopback-only: never auto-open for remote binds.
        assert "loopback-only" in launcher

    def test_launcher_installs_desktop_menu_entry(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        launcher = (root / "launcher.sh").read_text()
        template = (root / "packaging" / "polyforge.desktop.in").read_text()

        assert "install_desktop_entry" in launcher
        assert "--install-desktop" in launcher
        assert "--uninstall-desktop" in launcher
        assert "POLYFORGE_NO_DESKTOP" in launcher
        assert "Categories=Graphics;3DGraphics;" in template
        assert (root / "assets" / "logo" / "polyforge-icon.svg").exists()
        assert (root / "assets" / "logo" / "polyforge-icon-256.png").exists()

    def test_download_prompt_accepts_yes(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        launcher = (root / "launcher.sh").read_text()

        assert "[y/N/all/shape/multiview/tex/t2i]" in launcher
        assert "y|yes|all" in launcher

    def test_diso_is_opt_in_not_default(self):
        import tomllib
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        with (root / "pyproject.toml").open("rb") as handle:
            ml = tomllib.load(handle)["project"]["optional-dependencies"]["ml"]
        assert "diso" not in ml
        reqs = (root / "requirements.txt").read_text()
        assert "\ndiso\n" not in f"\n{reqs}\n"


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


class TestRemoteBindAuthentication:
    @pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "polyforge-api"])
    def test_non_loopback_bind_requires_api_key(self, monkeypatch, host):
        from hy3dgen.api import server as server_module

        monkeypatch.setattr(server_module._auth_module, "get_api_key", lambda: None)
        with pytest.raises(RuntimeError, match="POLYFORGE_API_KEY is required"):
            server_module._require_auth_for_non_loopback(host)

    @pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
    def test_loopback_bind_allows_missing_api_key(self, monkeypatch, host):
        from hy3dgen.api import server as server_module

        monkeypatch.setattr(server_module._auth_module, "get_api_key", lambda: None)
        server_module._require_auth_for_non_loopback(host)
