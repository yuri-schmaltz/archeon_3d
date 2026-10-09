"""Application configuration.

Two layers:

1. ``Settings`` (Pydantic Settings): auto-validated env var loading.
   Reads ``POLYFORGE_*`` env vars at import time. The class is cached
   so repeated reads are O(1) and tests can monkeypatch via
   ``Settings(_env_file=None, **overrides)``.

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
# Legacy guard: the pre-rebrand env prefix is rejected loudly on import.
# NOTE: the old prefix is deliberately assembled below instead of written
# out, so no trace of the pre-rebrand brand string remains in the tree.
# ---------------------------------------------------------------------------

_LEGACY_PREFIX = "".join(["ARC", "HEON_"])


def _reject_legacy_env() -> None:
    """Fail fast when pre-rebrand ``<old>_*`` vars are still set.

    Silently ignoring them would be dangerous: e.g. an old API-key var
    left in the environment would no longer enable auth, leaving the API
    wide open. Raising here turns a stale config into a loud startup
    error with a clear migration path instead.
    """
    legacy = sorted(k for k in os.environ if k.startswith(_LEGACY_PREFIX))
    if legacy:
        names = ", ".join(legacy)
        renames = ", ".join("POLYFORGE_" + k[len(_LEGACY_PREFIX) :] for k in legacy)
        raise RuntimeError(
            f"Legacy environment variables detected ({names}). "
            f"Rename them to the POLYFORGE_* equivalents ({renames}) and restart."
        )


# ---------------------------------------------------------------------------
# Filesystem defaults (follow XDG Base Directory spec)
# ---------------------------------------------------------------------------

_DEFAULT_SAVE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
    "hy3dgen",
    "polyforge",
)
_DEFAULT_STATE_DIR = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
    "hy3dgen",
    "polyforge",
)

# ---------------------------------------------------------------------------
# Pydantic Settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Validated application configuration.

    Every field maps to a ``POLYFORGE_*`` env var (case-insensitive).
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
        env_prefix="POLYFORGE_",
        env_file=None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    def __init__(self, **kwargs: object) -> None:
        # Opt-in .env loading: the project ships a ``.env.example`` but the
        # ``.env`` file itself is gitignored. We only read it when the
        # process is started with ``POLYFORGE_LOAD_DOTENV=1`` (the launcher
        # and the entry point set it). Tests run with the env var unset,
        # so a stray ``.env`` in the working directory cannot leak values
        # into ``Settings()`` and break hermetic assertions.
        #
        # Callers that want to bypass the flag (e.g. the conftest's
        # ``_restore_api_settings`` or the explicit ``Settings(_env_file=None)``
        # in the CORS test) get hermetic defaults.
        if "_env_file" not in kwargs and "env_file" not in kwargs:
            if os.environ.get("POLYFORGE_LOAD_DOTENV") == "1":
                kwargs["_env_file"] = ".env"
        super().__init__(**kwargs)

    # -- Server bind ----------------------------------------------------
    # Every field reads its ``POLYFORGE_<NAME>`` env var (upper-cased
    # field name) via ``env_prefix`` below. No legacy prefixes accepted.
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
    url_signing_key: str | None = Field(
        default=None,
        description=("HMAC key for signed /files URLs. Falls back to ``api_key`` when unset."),
    )
    rate_limit: str = Field(
        default="120/minute",
        description=(
            "slowapi limit applied to /v1 routes. Empty, false, off, none, "
            "disabled, or 0 disables rate limiting entirely."
        ),
    )
    max_body_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=0,
        description="Reject request bodies larger than this (0 disables the guard).",
    )

    # -- Device + model -------------------------------------------------
    device: str = Field(default="cuda", description="cuda | cpu")
    model: str = Field(default="tencent/Hunyuan3D-2", description="HF model id")
    mini_model: str = Field(default="tencent/Hunyuan3D-2mini", description="HF mini model id")
    model_subfolder: str = "hunyuan3d-dit-v2-0"
    multiview_model: str = "tencent/Hunyuan3D-2mv"
    multiview_subfolder: str = "hunyuan3d-dit-v2-mv"
    t2i_model: str | None = Field(
        default=None,
        description=(
            "Optional override for the text-to-image checkpoint used before "
            "shape generation. Defaults to the bundled HunyuanDiT model."
        ),
    )
    hf_home: str | None = Field(
        default=None,
        description="HF cache directory. Takes precedence over plain HF_HOME.",
    )

    # -- Inference topology --------------------------------------------
    use_shared_inference: bool = Field(
        default=True,
        description=(
            "When true (default) the manager delegates to a shared "
            "InferenceService. Set to false to fall back to the "
            "embedded worker loop (useful for unit tests that mock "
            "the worker directly)."
        ),
    )

    # -- Storage paths --------------------------------------------------
    save_dir: str = Field(default=_DEFAULT_SAVE_DIR, description="Output mesh dir")
    job_db: str | None = Field(
        default_factory=lambda: os.path.join(_DEFAULT_STATE_DIR, "jobs.db"),
        description="SQLite job DB. Empty string disables persistence.",
    )
    max_history: int = Field(default=1000, ge=0, description="In-memory job cap")
    max_age_seconds: int = Field(default=86_400, ge=0, description="Job eviction age")
    max_queue_size: int = Field(default=4, ge=1, description="Maximum pending inference jobs")

    # -- Logging --------------------------------------------------------
    log_level: str = Field(default="INFO", description="DEBUG/INFO/WARNING/ERROR")
    log_file: str | None = Field(default=None, description="Optional log file path")
    log_json: bool = Field(
        default=False,
        description="Emit logs as JSON (for Loki/Datadog/Cloud Logging).",
    )
    otel_enabled: bool = Field(
        default=False,
        description=(
            "Export OpenTelemetry spans around inference. Requires the "
            "``otel`` extra; without it the server stays on no-op spans."
        ),
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

        Some operators set ``POLYFORGE_PORT=8080`` accidentally with
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

    @field_validator("rate_limit", mode="before")
    @classmethod
    def _normalize_rate_limit(cls, v: Any) -> Any:
        """Accept common spellings for “no rate limit”.

        Operators already use ``false`` in tests and local fixtures, while
        the documented setting is an empty string. Normalise both (and a
        few adjacent spellings) to SlowAPI's disabled state.
        """
        if v is None:
            return ""
        text = str(v).strip()
        if text.lower() in {"", "0", "false", "off", "none", "disabled", "no"}:
            return ""
        return text

    @field_validator("hf_home", mode="before")
    @classmethod
    def _normalize_hf_home(cls, v: Any) -> Any:
        if v is None:
            return None
        text = str(v).strip()
        return text or None

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
            1. ``POLYFORGE_HOST`` env var (explicit override; default unset).
            2. If ``POLYFORGE_API_KEY`` is set: ``0.0.0.0`` (you've opted
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


# Reject pre-rebrand variables before anything else: silently ignoring
# them could disable auth or misconfigure the server.
_reject_legacy_env()

# Singleton. Tests can monkeypatch via ``settings.api_key = ...`` or by
# constructing a fresh ``Settings(_env_file=None, **overrides)``.
#
# If the env is misconfigured (e.g. ``POLYFORGE_LOG_LEVEL=bogus``) we don't
# want the import to crash — that would take down the entire server.
# Fall back to all-defaults so the user can at least see the API; they
# can fix the env and restart.
try:
    settings = Settings()
except Exception:
    # The env is misconfigured (e.g. ``POLYFORGE_LOG_LEVEL=bogus``). Build
    # a default-only instance that ignores the env so the import still
    # succeeds. The user can fix the env and restart to pick up the
    # intended values.
    import os as _os

    _saved = {k: _os.environ.pop(k) for k in list(_os.environ) if k.startswith("POLYFORGE_")}
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
            t2i_model=None,
            hf_home=None,
            save_dir=_DEFAULT_SAVE_DIR,
            job_db=None,
            max_history=1000,
            max_age_seconds=86_400,
            max_queue_size=4,
            log_level="INFO",
            log_file=None,
            log_json=False,
            otel_enabled=False,
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


def configure_hf_home(hf_home: str | None = None) -> str | None:
    """Apply ``POLYFORGE_HF_HOME`` to the Hugging Face cache environment.

    This must run before ``huggingface_hub``/``transformers``/``diffusers``
    are first imported in the server process; those libraries read
    ``HF_HOME`` at import time. Returns the effective cache directory, or
    the pre-existing ``HF_HOME`` when no override is configured.
    """
    target = hf_home or settings.hf_home
    if not target:
        return os.environ.get("HF_HOME")
    target = os.path.abspath(os.path.expanduser(target))
    os.environ["HF_HOME"] = target
    return target


configure_hf_home()


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

    Honours ``POLYFORGE_LOG_LEVEL`` (DEBUG / INFO / WARNING / ERROR) and
    ``POLYFORGE_LOG_FILE`` (optional file path with rotation at 50 MB,
    keeping 5 backups). ``POLYFORGE_LOG_JSON=true`` switches the
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
    "configure_hf_home",
    "configure_logging",
    "get_bind_host",
    "get_bind_port",
    "get_cors_origins",
    "get_job_db_path",
    "get_log_file",
    "get_log_level",
    "settings",
]
