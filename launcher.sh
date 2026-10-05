#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Archeon 3D — one-shot smart launcher
#
# No arguments required. Detects state, fixes gaps, then runs:
#
#   1. Picks up the project's ``.venv`` (or creates one).
#   2. Verifies Python is in the supported range (3.10–3.12).
#   3. Installs/updates the backend (``pip install -e .``) and the
#      ``[ml]`` extra so the inference worker can load weights when
#      a job is submitted. Skips already-satisfied dependencies.
#   4. Runs ``npm install`` + ``npm run build`` for the frontend if
#      ``archeon_frontend/dist/`` is missing or older than its
#      sources.
#   5. Boots the Archeon API on ``http://127.0.0.1:8081`` (override
#      via ``ARCHEON_PORT`` / ``ARCHEON_HOST`` env vars).
#
# Re-runs are cheap: subsequent invocations only reinstall if the
# dependency manifest (pyproject.toml / requirements.txt / package.json)
# changed since the last successful run, recorded in
# ``.archeon_launcher.stamp``.
#
# Environment variables (all optional):
#   ARCHEON_HOST        bind host         (default: 127.0.0.1)
#   ARCHEON_PORT        bind port           (default: 8081)
#   ARCHEON_API_KEY     X-API-Key gate     (default: off for local dev)
#   ARCHEON_NO_ML       skip the [ml] extra (default: unset)
#   ARCHEON_NO_FRONTEND skip the npm build (default: unset)
#   ARCHEON_FORCE_REINSTALL touch the stamp to force reinstall
# -----------------------------------------------------------------------------

set -euo pipefail

# --- paths --------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
VENV_DIR="$SCRIPT_DIR/.venv"
STAMP_FILE="$SCRIPT_DIR/.archeon_launcher.stamp"
PYPROJECT="$SCRIPT_DIR/pyproject.toml"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
FRONTEND_DIR="$SCRIPT_DIR/archeon_frontend"
FRONTEND_DIST="$FRONTEND_DIR/dist"
PACKAGE_JSON="$FRONTEND_DIR/package.json"
LOG_DIR="$SCRIPT_DIR/.archeon_logs"

mkdir -p "$LOG_DIR"

# --- logging helpers ---------------------------------------------------------
_ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { printf '[%s] %s\n' "$(_ts)" "$*"; }
warn() { printf '[%s] ⚠ %s\n' "$(_ts)" "$*" >&2; }
die() { printf '[%s] ✗ %s\n' "$(_ts)" "$*" >&2; exit 1; }

# --- 1. pick a Python ---------------------------------------------------------
PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    die "Python interpreter '$PYTHON_BIN' not found on PATH."
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
log "Detected Python $PY_VERSION ($PYTHON_BIN)"

# Spec requires >=3.10,<3.13.
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION##*.}"
if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 10) || (PY_MAJOR == 3 && PY_MINOR >= 13) )); then
    die "Python $PY_VERSION is outside the supported range 3.10–3.12."
fi

# --- 2. create / refresh the venv --------------------------------------------
needs_venv_create=0
if [[ ! -d "$VENV_DIR" ]]; then
    needs_venv_create=1
elif [[ ! -x "$VENV_DIR/bin/python" ]]; then
    warn "Existing $VENV_DIR is broken; recreating."
    rm -rf "$VENV_DIR"
    needs_venv_create=1
fi

if (( needs_venv_create )); then
    log "Creating venv at $VENV_DIR (this may take a minute)…"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Pin python to the venv's interpreter for the rest of the run.
PYTHON="$(which python)"
PIP=$(python -c 'import sys; print(sys.executable.replace("python", "pip", 1))' 2>/dev/null || echo "$VENV_DIR/bin/pip")

# Upgrade pip + wheel first; wheel avoids egg-only installs.
log "Upgrading pip + wheel + setuptools…"
"$PYTHON" -m pip install --quiet --upgrade pip wheel setuptools

# --- 3. decide whether to reinstall the backend -------------------------------
manifest_changed() {
    # Returns 0 if any of the tracked files is newer than the stamp.
    local stamp="$1"
    shift
    local f
    [[ ! -f "$stamp" ]] && return 0
    for f in "$@"; do
        [[ -f "$f" ]] || continue
        if [[ "$f" -nt "$stamp" ]]; then
            return 0
        fi
    done
    return 1
}

BACKEND_MANIFESTS=("$PYPROJECT" "$REQUIREMENTS")
if [[ "${ARCHEON_FORCE_REINSTALL:-}" == "1" ]]; then
    manifest_changed=1
fi

# pip install logic: prefer the [ml] extra when possible, fall back to
# requirements.txt if pyproject.toml can't be parsed.
#
# A few packages (notably ``diso``) declare a build-time dependency on
# ``torch`` even though they don't actually need it. Pip's build
# isolation tries to install just the build requirements into a sandbox
# which doesn't have torch → the build fails. Worse, ``diso`` also
# fails to build when the system CUDA differs from the one torch was
# compiled against. We work around both with --no-build-isolation
# plus an opportunistic ``mc`` fallback at runtime; see
# ``hy3dgen.inference._generate``.
do_backend_install() {
    log "Installing backend (editable + [ml] extra)…"
    local extra="dev"
    if [[ "${ARCHEON_NO_ML:-}" != "1" ]]; then
        extra="ml,dev"
    fi

    # Step 1: torch + torchvision first. They have the heaviest CUDA
    # wheels and are what most downstream builds (diso, mmgp) assume
    # is available at build time.
    if [[ "${ARCHEON_NO_ML:-}" != "1" ]]; then
        log "Pre-installing torch + torchvision (large CUDA wheels)…"
        if ! "$PYTHON" -m pip install --quiet torch torchvision; then
            warn "torch install failed; will continue with the editable install and hope for the best."
        fi
    fi

    # Step 2: editable install with the rest. --no-build-isolation so
    # the build sandbox can see torch and any other already-installed
    # packages, sidestepping the diso problem.
    if "$PYTHON" -m pip install --quiet --no-build-isolation -e ".[$extra]"; then
        return 0
    fi

    warn "Editable install failed; some heavy ML packages (diso) may need a matching CUDA toolkit."
    warn "Retrying without [ml] so the API still comes up."

    # Try without [ml] — the inference code auto-detects the absence of
    # ``diso`` and falls back to ``mc`` marching cubes, so we keep most
    # functionality.
    if "$PYTHON" -m pip install --quiet --no-build-isolation -e ".[dev]"; then
        warn "Installed API-only build. ML inference will work but use the 'mc' surface extractor."
        export ARCHEON_NO_ML=1
        return 0
    fi

    if [[ -f "$REQUIREMENTS" ]]; then
        if "$PYTHON" -m pip install --quiet --no-build-isolation -r "$REQUIREMENTS"; then
            return 0
        fi
    fi
    die "Backend install failed (tried [ml,dev], [dev], and requirements.txt)."
}

if [[ "${ARCHEON_NO_ML:-}" == "1" ]]; then
    BACKEND_INSTALL_CMD=("$PYTHON" -m pip install --quiet -e ".[dev]")
else
    BACKEND_INSTALL_CMD=("$PYTHON" -m pip install --quiet -e ".[ml,dev]")
fi

if manifest_changed "$STAMP_FILE" "${BACKEND_MANIFESTS[@]}"; then
    if [[ "${ARCHEON_NO_ML:-}" == "1" ]]; then
        "$PYTHON" -m pip install --quiet -e ".[dev]"
    else
        do_backend_install || die "Backend install failed."
    fi
    touch "$STAMP_FILE"
else
    log "Backend dependencies up-to-date (stamp $STAMP_FILE)."
fi

# --- 4. ensure the package itself imports -------------------------------------
if ! "$PYTHON" -c "import hy3dgen" >/dev/null 2>&1; then
    warn "hy3dgen not importable; reinstalling editable."
    "$PYTHON" -m pip install --quiet -e ".[dev]" || die "Reinstall failed."
fi

# --- 5. frontend build (skip if disabled) -------------------------------------
if [[ "${ARCHEON_NO_FRONTEND:-}" != "1" ]]; then
    if ! command -v node >/dev/null 2>&1; then
        warn "Node.js not found on PATH; skipping frontend build. Install Node 20+ to enable."
    else
        NODE_VERSION="$(node --version)"
        log "Node $NODE_VERSION detected"
        needs_npm_install=0
        if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
            needs_npm_install=1
        elif manifest_changed "$STAMP_FILE" "$PACKAGE_JSON"; then
            needs_npm_install=1
        fi

        if (( needs_npm_install )); then
            log "Installing frontend dependencies (npm install)…"
            ( cd "$FRONTEND_DIR" && npm install --no-audit --no-fund )
        fi

        if manifest_changed "$STAMP_FILE" "$PACKAGE_JSON" || [[ ! -d "$FRONTEND_DIST" ]]; then
            log "Building frontend (npm run build)…"
            ( cd "$FRONTEND_DIR" && npm run build )
        else
            log "Frontend dist present and fresh; skipping build."
        fi
    fi
fi

# Final stamp update so we don't reinstall on every invocation.
touch "$STAMP_FILE"

# --- 6. launch the API --------------------------------------------------------
ARCHEON_HOST="${ARCHEON_HOST:-127.0.0.1}"
ARCHEON_PORT="${ARCHEON_PORT:-8081}"
export ARCHEON_HOST
export ARCHEON_PORT
if [[ -n "${ARCHEON_API_KEY:-}" ]]; then
    export ARCHEON_API_KEY
    log "API key auth: ENABLED (X-API-Key required)"
else
    log "API key auth: disabled (binding $ARCHEON_HOST is loopback)"
fi

# Honour SIGINT / SIGTERM for graceful shutdown.
trap 'log "Caught signal — shutting down."; kill -TERM "$API_PID" 2>/dev/null || true; wait "$API_PID" 2>/dev/null || true; exit 0' INT TERM

log "Starting Archeon API on http://$ARCHEON_HOST:$ARCHEON_PORT"
log "Logs: tail -f $LOG_DIR/api.log"

# Run uvicorn directly from the venv so re-installs are picked up immediately.
PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    "$VENV_DIR/bin/python" -m uvicorn \
    hy3dgen.api.server:app \
    --host "$ARCHEON_HOST" \
    --port "$ARCHEON_PORT" \
    >> "$LOG_DIR/api.log" 2>&1 &
API_PID=$!

# Brief readiness probe so users see a clear OK / ERROR before exiting.
for _ in {1..40}; do
    if curl -fsS "http://${ARCHEON_HOST}:${ARCHEON_PORT}/health" >/dev/null 2>&1; then
        log "API ready (pid $API_PID)."
        break
    fi
    if ! kill -0 "$API_PID" 2>/dev/null; then
        warn "API process exited. Last 30 log lines:"
        tail -n 30 "$LOG_DIR/api.log" >&2 || true
        exit 1
    fi
    sleep 0.5
done

log "Press Ctrl+C to stop."
wait "$API_PID"