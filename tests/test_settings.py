"""Tests for the Pydantic Settings-based config."""
from __future__ import annotations

import pytest
import pydantic_core
import pydantic


class TestSettingsDefaults:
    def test_default_port(self, monkeypatch, reload_config):
        monkeypatch.delenv("POLYFORGE_PORT", raising=False)
        cfg = reload_config()
        s = cfg.Settings()
        assert s.port == 8081

    def test_default_log_level(self, monkeypatch, reload_config):
        monkeypatch.delenv("POLYFORGE_LOG_LEVEL", raising=False)
        cfg = reload_config()
        s = cfg.Settings()
        assert s.log_level == "INFO"

    def test_default_device(self, monkeypatch, reload_config):
        monkeypatch.delenv("POLYFORGE_DEVICE", raising=False)
        cfg = reload_config()
        s = cfg.Settings()
        assert s.device == "cuda"

    def test_default_cors_origins(self, monkeypatch, reload_config):
        monkeypatch.delenv("POLYFORGE_CORS_ORIGINS", raising=False)
        cfg = reload_config()
        s = cfg.Settings()
        assert s.cors_origins == "*"
        assert s.cors_origins_list == ["*"]


class TestSettingsEnvOverrides:
    def test_port_from_env(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_PORT", "9999")
        cfg = reload_config()
        s = cfg.Settings()
        assert s.port == 9999

    def test_api_key_from_env(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_API_KEY", "secret")
        cfg = reload_config()
        s = cfg.Settings()
        assert s.api_key == "secret"

    def test_cors_list_from_env(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_CORS_ORIGINS", "http://a,http://b")
        cfg = reload_config()
        s = cfg.Settings()
        assert s.cors_origins_list == ["http://a", "http://b"]

    def test_log_level_uppercased(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_LOG_LEVEL", "warning")
        cfg = reload_config()
        s = cfg.Settings()
        assert s.log_level == "WARNING"

    def test_bad_log_level_falls_back_on_import(self, monkeypatch, reload_config):
        """A bogus env var does not crash the import; settings falls back to defaults."""
        monkeypatch.setenv("POLYFORGE_LOG_LEVEL", "bogus")
        cfg = reload_config()
        # Reload re-executes the module body, which wraps the ``Settings()``
        # call in a try/except. The reload's singleton therefore falls back
        # to all defaults.
        assert cfg.settings.log_level == "INFO"

    def test_bad_device_falls_back_on_import(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_DEVICE", "gpu")
        cfg = reload_config()
        assert cfg.settings.device == "cuda"


class TestSettingsBindHost:
    def test_default_is_localhost(self, monkeypatch, reload_config):
        monkeypatch.delenv("POLYFORGE_HOST", raising=False)
        monkeypatch.delenv("POLYFORGE_API_KEY", raising=False)
        cfg = reload_config()
        s = cfg.Settings()
        assert s.bind_host == "127.0.0.1"

    def test_api_key_unlocks_wildcard(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_API_KEY", "x")
        monkeypatch.delenv("POLYFORGE_HOST", raising=False)
        cfg = reload_config()
        s = cfg.Settings()
        assert s.bind_host == "0.0.0.0"

    def test_explicit_host_wins(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_API_KEY", "x")
        monkeypatch.setenv("POLYFORGE_HOST", "10.0.0.1")
        cfg = reload_config()
        s = cfg.Settings()
        assert s.bind_host == "10.0.0.1"


class TestSettingsJobDbPath:
    def test_empty_string_is_none(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_JOB_DB", "")
        cfg = reload_config()
        s = cfg.Settings()
        assert s.job_db_path is None

    def test_explicit_path(self, monkeypatch, reload_config):
        monkeypatch.setenv("POLYFORGE_JOB_DB", "/tmp/jobs.db")
        cfg = reload_config()
        s = cfg.Settings()
        assert s.job_db_path == "/tmp/jobs.db"


class TestConfigureLogging:
    def test_json_formatter(self, monkeypatch, reload_config):
        """When POLYFORGE_LOG_JSON=true, the formatter emits JSON."""
        monkeypatch.setenv("POLYFORGE_LOG_JSON", "true")
        cfg = reload_config()
        cfg.configure_logging()
        import logging
        for h in logging.getLogger().handlers:
            # The JSON formatter's _fmt starts with `{`; the default
            # formatter's _fmt starts with the timestamp pattern.
            if h.formatter:
                assert h.formatter._fmt.startswith("{"), (
                    f"expected JSON formatter, got: {h.formatter._fmt!r}"
                )


@pytest.fixture
def reload_config(monkeypatch):
    """Re-import hy3dgen.api.config with current env, returning the module."""
    def _reload():
        from hy3dgen.api import config as config_module
        import importlib
        importlib.reload(config_module)
        return config_module
    return _reload
