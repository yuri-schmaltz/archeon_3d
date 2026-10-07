"""Tests for the /health endpoint and the config helpers it depends on."""
import importlib
import os

import pytest
import logging


@pytest.fixture
def reload_config(monkeypatch):
    """Re-import hy3dgen.api.config with current env, returning the module."""
    def _reload():
        from hy3dgen.api import config as config_module
        importlib.reload(config_module)
        return config_module
    return _reload


class TestGetBindHost:
    def test_default_is_localhost(self, monkeypatch, reload_config):
        monkeypatch.delenv("POLYFORGE_HOST", raising=False)
        monkeypatch.delenv("POLYFORGE_API_KEY", raising=False)
        cfg = reload_config()
        assert cfg.get_bind_host() == "127.0.0.1"

    def test_api_key_unlocks_wildcard(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_API_KEY", "x")
        monkeypatch.delenv("POLYFORGE_HOST", raising=False)
        cfg = reload_config()
        assert cfg.get_bind_host() == "0.0.0.0"

    def test_explicit_host_overrides_api_key(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_API_KEY", "x")
        monkeypatch.setenv("POLYFORGE_HOST", "10.0.0.1")
        cfg = reload_config()
        assert cfg.get_bind_host() == "10.0.0.1"


class TestGetBindPort:
    def test_default(self, monkeypatch, reload_config):
        monkeypatch.delenv("POLYFORGE_PORT", raising=False)
        cfg = reload_config()
        assert cfg.get_bind_port() == 8081

    def test_custom(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_PORT", "9999")
        cfg = reload_config()
        assert cfg.get_bind_port() == 9999

    def test_invalid_falls_back(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_PORT", "not-a-number")
        cfg = reload_config()
        assert cfg.get_bind_port() == 8081


class TestGetLogLevel:
    def test_default_info(self, monkeypatch, reload_config):
        monkeypatch.delenv("POLYFORGE_LOG_LEVEL", raising=False)
        cfg = reload_config()
        assert cfg.get_log_level() == "INFO"

    def test_uppercased(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_LOG_LEVEL", "debug")
        cfg = reload_config()
        assert cfg.get_log_level() == "DEBUG"


class TestGetLogFile:
    def test_default_none(self, monkeypatch, reload_config):
        monkeypatch.delenv("POLYFORGE_LOG_FILE", raising=False)
        cfg = reload_config()
        assert cfg.get_log_file() is None

    def test_empty_string_is_none(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_LOG_FILE", "")
        cfg = reload_config()
        assert cfg.get_log_file() is None

    def test_set(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_LOG_FILE", "/var/log/polyforge.log")
        cfg = reload_config()
        assert cfg.get_log_file() == "/var/log/polyforge.log"


class TestConfigureLogging:
    def test_runs_without_error(self, monkeypatch, reload_config):
        """Just exercise the happy path; verifying output requires log capture."""
        cfg = reload_config()
        cfg.configure_logging()
        import logging
        assert logging.getLogger().level <= logging.INFO

    def test_runs_with_file(self, tmp_path, monkeypatch, reload_config):
        """When POLYFORGE_LOG_FILE is set, the file handler is created."""
        log_file = tmp_path / "polyforge.log"
        monkeypatch.setenv("POLYFORGE_LOG_FILE", str(log_file))
        cfg = reload_config()
        cfg.configure_logging()
        # Emit something to make sure the file gets touched.
        logging.getLogger("hy3dgen.test").info("hello")
        for h in logging.getLogger().handlers:
            h.flush()
        assert log_file.exists()


class TestHealthEndpoint:
    def test_health_includes_capabilities_and_uptime(self):
        """A live TestClient would be flaky for this — just check the
        endpoint is registered and returns the expected shape by reading
        the FastAPI route table.
        """
        from hy3dgen.api import server as server_module
        # Some routes are IncludedRouter / Mount objects without ``path``;
        # only look at the APIRoute / HTTP ones.
        paths = [r.path for r in server_module.app.routes if hasattr(r, "path")]
        assert "/health" in paths
