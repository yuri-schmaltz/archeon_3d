"""Tests for hy3dgen.version module and version checking utility."""

import re
from unittest.mock import MagicMock, patch

from hy3dgen.version import (
    GITHUB_API_URL,
    __version__,
    _parse_version,
    check_for_updates,
    get_current_version,
)


class TestGetCurrentVersion:
    def test_returns_string(self):
        result = get_current_version()
        assert isinstance(result, str)

    def test_returns_valid_semver(self):
        v = get_current_version()
        assert re.match(r"\d+\.\d+\.\d+", v), f"Not a valid semver: {v}"

    def test_fallback_matches_module_version(self):
        """When package metadata is unavailable, __version__ is used."""
        from importlib.metadata import PackageNotFoundError

        with patch("hy3dgen.version.pkg_version", side_effect=PackageNotFoundError("hy3dgen")):
            assert get_current_version() == __version__


class TestParseVersion:
    def test_simple_version(self):
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_with_v_prefix(self):
        assert _parse_version("v2.1.0") == (2, 1, 0)

    def test_invalid_returns_zero(self):
        assert _parse_version("invalid") == (0, 0, 0)

    def test_empty_returns_zero(self):
        assert _parse_version("") == (0, 0, 0)

    def test_comparison_works(self):
        assert _parse_version("v2.1.0") > _parse_version("v2.0.0")
        assert _parse_version("1.0.0") < _parse_version("1.0.1")
        assert _parse_version("v3.0.0") == _parse_version("3.0.0")


class TestCheckForUpdates:
    def test_returns_none_when_up_to_date(self):
        mock_response = MagicMock()
        mock_response.read.return_value = (
            b'{"tag_name": "v0.0.1", "html_url": "https://example.com"}'
        )
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = check_for_updates()
            assert result is None  # Current 2.0.0 > 0.0.1

    def test_returns_info_when_update_available(self):
        mock_response = MagicMock()
        mock_response.read.return_value = (
            b'{"tag_name": "v99.0.0", "html_url": "https://example.com/release"}'
        )
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = check_for_updates()
            assert result is not None
            assert result["latest"] == "v99.0.0"
            assert result["current"] == get_current_version()
            assert result["url"] == "https://example.com/release"

    def test_returns_none_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=Exception("network error")):
            result = check_for_updates()
            assert result is None  # Never raises

    def test_returns_none_on_timeout(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            result = check_for_updates()
            assert result is None

    def test_github_api_url_is_valid(self):
        assert "api.github.com" in GITHUB_API_URL
        assert "/releases/latest" in GITHUB_API_URL
