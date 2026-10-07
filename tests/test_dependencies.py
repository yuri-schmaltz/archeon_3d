"""Keep the two dependency manifests aligned."""

from __future__ import annotations

from pathlib import Path

import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent


def _requirements_text() -> str:
    return (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")


def _pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_ml_dependency_bounds_match_requirements():
    requirements = _requirements_text()
    ml = _pyproject()["project"]["optional-dependencies"]["ml"]

    assert "transformers>=4.50,<5" in requirements
    assert "transformers>=4.50,<5" in ml
    assert "diffusers>=0.39,<0.40" in requirements
    assert "diffusers>=0.39,<0.40" in ml


def test_sentencepiece_is_declared_for_fresh_installs():
    requirements = _requirements_text()
    ml = _pyproject()["project"]["optional-dependencies"]["ml"]

    assert "\nsentencepiece\n" in f"\n{requirements}\n"
    assert "sentencepiece" in ml


def test_otel_extra_exists():
    extras = _pyproject()["project"]["optional-dependencies"]

    assert set(extras["otel"]) >= {
        "opentelemetry-api",
        "opentelemetry-sdk",
        "opentelemetry-exporter-otlp",
    }
