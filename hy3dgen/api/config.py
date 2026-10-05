"""Application configuration.

Two layers:

1. ``Settings`` (Pydantic Settings): auto-validated env var loading.
   Reads ``ARCHEON_*`` env vars (and the legacy ``XDG_*`` paths) at
   import time. The class is cached so repeated reads are O(1) and
   tests can monkeypatch via ``Settings(_env_file=None, **overrides)``.

2. Backward-compatible module-level helpers (``get_job_db_path``,
   ``get_bind_host``, etc.) that wrap ``Settings``. These are kept
   because they're called from many places (``server.py``, the
   CLI, tests); the long-term migration is to inject ``Settings``
   directly into the FastAPI app.

The ``SAVE_DIR`` constant is still computed at import time because
the ``/files`` static mount in ``server.py`` needs a real path
**before** the lifespan starts. Pydantic Settings can give us that
too (``settings.save_dir``), but the module-level constant is
simpler to pass to ``StaticFiles(directory=SAVE_DIR)``.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Filesystem defaults (follow XDG Base Directory spec)
# ---------------------------------------------------------------------------

_DEFAULT_SAVE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
    "hy3dgen",
    "archeon",
)
_DEFAULT_STATE_DIR = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
    "hy3dgen",
    "archeon",
)

# ---------------------------------------------------------------------------
# Pydantic Settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Validated application configuration.

    Every field maps to an ``ARCHEON_*`` env var (case-insensitive).
    Pydantic Settings handles the parsing, type coercion, and validation
    in one go. Default values match the behaviour of the previous
    module-level helpers so this is a drop-in replacement.

    Usage::

        from hy3dgen.api.config import settings

        settings.api_key  # str | None
        settings.save_dir  # Path
        settings.job_db_path  # Path | None
        settings.bind_host  # str (precedence-aware)
    """

    model_config = SettingsConfigDict(
        env_prefix="ARCHEON_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Server bind ----------------------------------------------------
    host: str | None = Field(default=None, description="Override bind host")
    port: int = Field(default=8081, ge=1, le=65535, description="Bind port")
    workers: int = Field(default=1, ge=1, description="Uvicorn workers")

    # -- Auth + CORS ----------------------------------------------------
    api_key: str | None = Field(
        default=None,
        description="If set, requires X-API-Key header. Empty disables auth.",
    )
    cors_origins: str = Field(
        default="*",
        description="Comma-separated CORS origins. ``*`` opens it (dev only).",
    )
    allow_credentials: bool = Field(
        default=False,
        description="Enable CORS credentials (cookies, auth headers).",
    )

    # -- Device + model -------------------------------------------------
    device: str = Field(default="cuda", description="cuda | cpu")
    model: str = Field(default="tencent/Hunyuan3D-2", description="HF model id")
    mini_model: str = Field(default="tencent/Hunyuan3D-2mini", description="HF mini model id")
    model_subfolder: str = "hunyuan3d-dit-v2-0"
    multiview_model: str = "tencent/Hunyuan3D-2mv"
    multiview_subfolder: str = "hunyuan3d-dit-v2-mv"
    hf_home: str | None = Field(default=None, description="HF cache directory")

    # -- Storage paths --------------------------------------------------
    save_dir: str = Field(default=_DEFAULT_SAVE_DIR, description="Output mesh dir")
    job_db: str | None = Field(
        default_factory=lambda: os.path.join(_DEFAULT_STATE_DIR, "jobs.db"),
        description="SQLite job DB. Empty string disables persistence.",
    )
    max_history: int = Field(default=1000, ge=0, description="In-memory job cap")
    max_age_seconds: int = Field(default=86_400, ge=0, description="Job eviction age")

    # -- Logging --------------------------------------------------------
    log_level: str = Field(default="INFO", description="DEBUG/INFO/WARNING/ERROR")
    log_file: str | None = Field(default=None, description="Optional log file path")
    log_json: bool = Field(
        default=False,
        description="Emit logs as JSON (for Loki/Datadog/Cloud Logging).",
    )

    # -- Generation defaults ------------------------------------------
    default_seed: int = Field(default=1234)
    default_steps: int = Field(default=50, ge=1, le=100)
    default_guidance: float = Field(default=5.0, ge=1.0, le=20.0)
    default_octree: int = Field(default=256, ge=16, le=512)
    default_face_count: int = Field(default=40_000, ge=100, le=1_000_000)

    # ------------------------------------------------------------------

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(
                f"log_level must be one of DEBUG/INFO/WARNING/ERROR/CRITICAL, got {v!r}"
            )
        return v

    @field_validator("device")
    @classmethod
    def _check_device(cls, v: str) -> str:
        v = v.lower()
        if v not in {"cuda", "cpu"}:
            raise ValueError(f"device must be 'cuda' or 'cpu', got {v!r}")
        return v

    @field_validator("port", mode="before")
    @classmethod
    def _parse_port(cls, v: Any) -> Any:
        """Fall back to default if the env var isn't a valid int.

        Some operators set ``ARCHEON_PORT=8080`` accidentally with
        whitespace or a typo; we'd rather serve on 8081 than crash at
        startup. Pass an ``int`` to bypass this validator.
        """
        if v is None or v == "":
            return 8081
        if isinstance(v, int):
            return v
        try:
            return int(str(v).strip())
        except (TypeError, ValueError):
            return 8081

    @field_validator("cors_origins")
    @classmethod
    def _strip_cors(cls, v: str) -> str:
        return v.strip()

    @field_validator("save_dir", mode="after")
    @classmethod
    def _ensure_save_dir(cls, v: str) -> str:
        v = v.strip() or _DEFAULT_SAVE_DIR
        Path(v).mkdir(parents=True, exist_ok=True)
        return v

    # ---- Computed properties ----------------------------------------

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse ``cors_origins`` into a list."""
        if self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def bind_host(self) -> str:
        """Resolved bind host.

        Precedence (highest first):
            1. ``ARCHEON_HOST`` env var (explicit override; default unset).
            2. If ``ARCHEON_API_KEY`` is set: ``0.0.0.0`` (you've opted
               in to expose the API beyond localhost).
            3. Otherwise: ``127.0.0.1`` (dev / untrusted default).
        """
        if self.host:
            return self.host
        if self.api_key:
            return "0.0.0.0"
        return "127.0.0.1"

    @property
    def job_db_path(self) -> str | None:
        """Resolved SQLite job DB path. ``""`` becomes ``None`` to disable."""
        if self.job_db is None or self.job_db == "":
            return None
        return self.job_db

    @property
    def log_file_path(self) -> str | None:
        """Resolved log file path. ``""`` or ``None`` means stderr only."""
        if self.log_file is None or self.log_file == "":
            return None
        return self.log_file


# Singleton. Tests can monkeypatch via ``settings.api_key = ...`` or by
# constructing a fresh ``Settings(_env_file=None, **overrides)``.
#
# If the env is misconfigured (e.g. ``ARCHEON_LOG_LEVEL=bogus``) we don't
# want the import to crash — that would take down the entire server.
# Fall back to all-defaults so the user can at least see the API; they
# can fix the env and restart.
try:
    settings = Settings()
except Exception:
    # The env is misconfigured (e.g. ``ARCHEON_LOG_LEVEL=bogus``). Build
    # a default-only instance that ignores the env so the import still
    # succeeds. The user can fix the env and restart to pick up the
    # intended values.
    import os as _os

    _saved = {k: _os.environ.pop(k) for k in list(_os.environ) if k.startswith("ARCHEON_")}
    try:
        # Pass _env_file explicitly so pydantic_settings doesn't read it.
        settings = Settings.model_construct(
            host=None,
            port=8081,
            workers=1,
            api_key=None,
            cors_origins="*",
            allow_credentials=False,
            device="cuda",
            model="tencent/Hunyuan3D-2",
            mini_model="tencent/Hunyuan3D-2mini",
            hf_home=None,
            save_dir=_DEFAULT_SAVE_DIR,
            job_db=None,
            max_history=1000,
            max_age_seconds=86_400,
            log_level="INFO",
            log_file=None,
            log_json=False,
            default_seed=1234,
            default_steps=50,
            default_guidance=5.0,
            default_octree=256,
            default_face_count=40_000,
        )
    finally:
        _os.environ.update(_saved)

# Static mounts and generation must use the same resolved output directory.
SAVE_DIR = settings.save_dir


# ---------------------------------------------------------------------------
# Backward-compatible helpers
# ---------------------------------------------------------------------------


def get_job_db_path() -> str | None:
    return settings.job_db_path


def get_cors_origins() -> list[str]:
    return settings.cors_origins_list


def get_log_level() -> str:
    return settings.log_level


def get_log_file() -> str | None:
    return settings.log_file_path


def get_bind_host() -> str:
    return settings.bind_host


def get_bind_port() -> int:
    return settings.port


def configure_logging() -> None:
    """Set up root logging once on startup.

    Honours ``ARCHEON_LOG_LEVEL`` (DEBUG / INFO / WARNING / ERROR) and
    ``ARCHEON_LOG_FILE`` (optional file path with rotation at 50 MB,
    keeping 5 backups). ``ARCHEON_LOG_JSON=true`` switches the
    formatter to structured JSON (for Loki / Datadog / Cloud Logging).

    Idempotent: safe to call from tests too.
    """
    level = settings.log_level
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = settings.log_file_path
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=50 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
        )
    if settings.log_json:
        fmt = '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
    else:
        fmt = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


# Re-exported for modules that need to monkeypatch SAVE_DIR (e.g. tests).
__all__ = [
    "SAVE_DIR",
    "Settings",
    "configure_logging",
    "get_bind_host",
    "get_bind_port",
    "get_cors_origins",
    "get_job_db_path",
    "get_log_file",
    "get_log_level",
    "settings",
]
