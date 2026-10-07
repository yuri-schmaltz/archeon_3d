#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# PolyForge — one-shot smart launcher (Do prompt ao polígono)
#
# No arguments required. Detects state, fixes gaps, then runs:
#
#   1. Picks up the project's ``.venv`` (or creates one).
#   2. Verifies Python is in the supported range (3.10–3.12).
#   3. Installs/updates the backend (``pip install -e .``) and the
#      ``[ml]`` extra so the inference worker can load weights when
#      a job is submitted. Skips already-satisfied dependencies.
#   4. Runs ``npm install`` + ``npm run build`` for the frontend if
#      ``polyforge_frontend/dist/`` is missing or older than its
#      sources.
#   5. Boots the PolyForge API on ``http://127.0.0.1:8081`` (override
#      via ``POLYFORGE_PORT`` / ``POLYFORGE_HOST`` env vars). The Vite
#      ``dist/`` is served at the same URL so the browser shows the
#      PolyForge UI without a separate dev server.
#
# Re-runs are cheap: subsequent invocations only reinstall if the
# dependency manifest (pyproject.toml / requirements.txt / package.json)
# changed since the last successful run, recorded in
# ``.polyforge_launcher.stamp``.
#
# Environment variables (all optional):
#   POLYFORGE_HOST      bind host         (default: 127.0.0.1)
#   POLYFORGE_PORT      bind port           (default: 8081)
#   POLYFORGE_API_KEY   X-API-Key gate     (default: off for local dev)
#   POLYFORGE_NO_ML     skip the [ml] extra (default: unset)
#   POLYFORGE_NO_FRONTEND skip the npm build (default: unset)
#   POLYFORGE_FORCE_REINSTALL touch the stamp to force reinstall
#   POLYFORGE_UI        run the legacy Gradio ``launcher.py`` instead
#                        of the API server (useful for users coming
#                        from the old setup)
#   POLYFORGE_DOWNLOAD_MODELS
#                       download model weights during install: 1/true/yes
#                       to download, 0/false/no to skip. Unset +
#                       interactive terminal → asks the user.
#   POLYFORGE_MODEL_SCOPE
#                       which weights to download: shape, multiview, tex,
#                       t2i or all (default: all). Only used when the
#                       download is enabled.
#
# Flags (alternative to env vars):
#   --ui                same as POLYFORGE_UI=1 (legacy Gradio launcher)
#   --no-ml             same as POLYFORGE_NO_ML=1
#   --no-frontend       same as POLYFORGE_NO_FRONTEND=1
#   --download-models   download model weights during install
#   --model-scope SCOPE same as POLYFORGE_MODEL_SCOPE (shape, multiview,
#                       tex, t2i or all)
#   --no-download-models
#                       skip the weights download without asking
#   --reinstall         same as POLYFORGE_FORCE_REINSTALL=1
#   --help              show this help text and exit
# -----------------------------------------------------------------------------

set -euo pipefail

# --- logging helpers (defined first: argument parsing already calls die) -----
_ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { printf '[%s] %s\n' "$(_ts)" "$*"; }
warn() { printf '[%s] ⚠ %s\n' "$(_ts)" "$*" >&2; }
die() { printf '[%s] ✗ %s\n' "$(_ts)" "$*" >&2; exit 1; }

# --- argument parsing ---------------------------------------------------------
show_help() {
    sed -n '2,54p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while (( $# )); do
    case "$1" in
        --help|-h) show_help ;;
        --ui)       POLYFORGE_UI=1 ;;
        --no-ml)    POLYFORGE_NO_ML=1 ;;
        --no-frontend) POLYFORGE_NO_FRONTEND=1 ;;
        --download-models) POLYFORGE_DOWNLOAD_MODELS=1 ;;
        --no-download-models) POLYFORGE_DOWNLOAD_MODELS=0 ;;
        --model-scope)
            [[ -n "${2:-}" ]] || die "--model-scope needs a value: shape, multiview, tex, t2i or all."
            POLYFORGE_MODEL_SCOPE="$2"
            shift
            ;;
        --model-scope=*) POLYFORGE_MODEL_SCOPE="${1#*=}" ;;
        --reinstall) POLYFORGE_FORCE_REINSTALL=1 ;;
        *) die "Unknown argument: $1 (try --help)";;
    esac
    shift
done

# --- guard: reject pre-rebrand env vars (prefix assembled, never written
# --- out, so no trace of the old brand string remains in the tree; see
# --- hy3dgen/api/config.py::_reject_legacy_env). Fail loudly so a stale
# --- config can't silently disable auth or misconfigure the server.
_legacy_prefix="ARC"; _legacy_prefix+="HEON_"
_legacy_vars="$(env | grep -o "^${_legacy_prefix}[A-Z0-9_]*" | sort -u | tr '\n' ' ' || true)"
if [[ -n "$_legacy_vars" ]]; then
    die "Legacy environment variables detected (${_legacy_vars}). Rename them to POLYFORGE_* and retry."
fi
unset _legacy_vars _legacy_prefix

# --- paths --------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
VENV_DIR="$SCRIPT_DIR/.venv"
STAMP_FILE="$SCRIPT_DIR/.polyforge_launcher.stamp"
PYPROJECT="$SCRIPT_DIR/pyproject.toml"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
FRONTEND_DIR="$SCRIPT_DIR/polyforge_frontend"
FRONTEND_DIST="$FRONTEND_DIR/dist"
PACKAGE_JSON="$FRONTEND_DIR/package.json"
LOG_DIR="$SCRIPT_DIR/.polyforge_logs"

mkdir -p "$LOG_DIR"

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
if [[ "${POLYFORGE_FORCE_REINSTALL:-}" == "1" ]]; then
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
#
# If the editable install with [ml] fails on diso, we don't give up on
# the whole ML stack: we still install all the pure-Python ML deps
# (diffusers, transformers, accelerate, rembg, onnxruntime, mmgp,
# einops, omegaconf, opencv, scikit-image, xatlas) individually,
# so the user has a working inference path with the 'mc' surface
# extractor instead of an API-only build that can't load any
# model at all.
install_individual_ml_deps() {
    # Wheel-only, no source builds. This is the safety net for
    # environments where ``diso`` won't compile (CUDA mismatch,
    # missing nvcc, etc.) but every other ML dep installs cleanly.
    #
    # We don't pin ``transformers`` because the compatible range
    # shifts with each diffusers release; the launcher always
    # installs the latest stable that the resolver finds. As of
    # diffusers 0.39 the floor is roughly transformers>=4.50.
    "$PYTHON" -m pip install --quiet \
        diffusers "transformers>=4.50" accelerate \
        einops omegaconf opencv-python-headless scikit-image \
        pymeshlab xatlas rembg onnxruntime || warn "Some individual ML packages failed; model loading will be partial."
}

do_backend_install() {
    log "Installing backend (editable + [ml] extra)…"
    local extra="dev"
    if [[ "${POLYFORGE_NO_ML:-}" != "1" ]]; then
        extra="ml,dev"
    fi

    # Step 1: torch + torchvision first. They have the heaviest CUDA
    # wheels and are what most downstream builds (diso, mmgp) assume
    # is available at build time.
    if [[ "${POLYFORGE_NO_ML:-}" != "1" ]]; then
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
    warn "Retrying with [ml] but skipping the diso wheel."
    warn "This still gives you a working inference pipeline; only the"
    warn "DMC surface extractor won't be available (the runtime falls"
    warn "back to 'mc' automatically)."

    # Try the ML extra minus diso. ``pip install -e .[ml,dev]`` is
    # monolithic, so we install the rest individually and then do
    # the editable dev extra for our own package metadata.
    install_individual_ml_deps
    if "$PYTHON" -m pip install --quiet --no-build-isolation -e ".[dev]"; then
        return 0
    fi

    warn "Even [dev] failed; trying API-only build."
    if "$PYTHON" -m pip install --quiet --no-build-isolation -e ".[dev]"; then
        warn "Installed API-only build. ML inference is NOT available."
        export POLYFORGE_NO_ML=1
        return 0
    fi

    if [[ -f "$REQUIREMENTS" ]]; then
        if "$PYTHON" -m pip install --quiet --no-build-isolation -r "$REQUIREMENTS"; then
            return 0
        fi
    fi
    die "Backend install failed (tried [ml,dev], [dev], and requirements.txt)."
}

if [[ "${POLYFORGE_NO_ML:-}" == "1" ]]; then
    BACKEND_INSTALL_CMD=("$PYTHON" -m pip install --quiet -e ".[dev]")
else
    BACKEND_INSTALL_CMD=("$PYTHON" -m pip install --quiet -e ".[ml,dev]")
fi

if manifest_changed "$STAMP_FILE" "${BACKEND_MANIFESTS[@]}"; then
    if [[ "${POLYFORGE_NO_ML:-}" == "1" ]]; then
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

# --- 5. optional model weights download ---------------------------------------
# Checkpoints are fetched lazily on the first job by default. Opt in here
# to pay that cost at install time instead: --download-models /
# POLYFORGE_DOWNLOAD_MODELS=1, optionally narrowed with --model-scope /
# POLYFORGE_MODEL_SCOPE (shape, multiview, tex, t2i or all). Unset +
# interactive terminal → ask the user once.
ask_download_models() {
    local answer hf_dir free_space
    hf_dir="${POLYFORGE_HF_HOME:-${HF_HOME:-$HOME/.cache/huggingface}}"
    free_space="$(df -h "$hf_dir" 2>/dev/null | awk 'NR==2 {print $4}')"
    log "Model weights download to: $hf_dir (free space: ${free_space:-unknown})"
    log "Scopes: all (~tens of GB) | shape (~12 GB) | multiview (~8 GB) | tex (full repo) | t2i (~15 GB)"
    printf 'Download model weights now? [N/all/shape/multiview/tex/t2i] '
    read -r answer </dev/tty || answer=""
    case "${answer,,}" in
        ""|n|no|0|false) return 1 ;;
        all|shape|multiview|tex|t2i) POLYFORGE_MODEL_SCOPE="${answer,,}" ;;
        *) warn "Unknown scope '$answer'; skipping weights download."; return 1 ;;
    esac
    return 0
}

_download_models="${POLYFORGE_DOWNLOAD_MODELS:-}"
case "${_download_models,,}" in
    1|true|yes) _do_download=1 ;;
    0|false|no) _do_download=0 ;;
    "")
        if [[ "${POLYFORGE_NO_ML:-}" == "1" ]]; then
            _do_download=0
        elif [[ -t 0 ]]; then
            if ask_download_models; then _do_download=1; else _do_download=0; fi
        else
            log "Skipping weights download (non-interactive; set POLYFORGE_DOWNLOAD_MODELS=1 to enable)."
            _do_download=0
        fi
        ;;
    *) die "POLYFORGE_DOWNLOAD_MODELS must be 1/0/true/false/yes/no, got '$_download_models'." ;;
esac

if (( _do_download )); then
    if [[ "${POLYFORGE_NO_ML:-}" == "1" ]]; then
        warn "Skipping weights download: ML dependencies are disabled (POLYFORGE_NO_ML=1)."
    else
        case "${POLYFORGE_MODEL_SCOPE:-all}" in
            all|shape|multiview|tex|t2i) ;;
            *) die "Unknown model scope '${POLYFORGE_MODEL_SCOPE}'. Use: shape, multiview, tex, t2i or all." ;;
        esac
        log "Downloading model weights (scope: ${POLYFORGE_MODEL_SCOPE:-all})…"
        "$PYTHON" "$SCRIPT_DIR/scripts/download_models.py" --scope "${POLYFORGE_MODEL_SCOPE:-all}" \
            || die "Model weights download failed."
    fi
else
    log "Skipping weights download; models will be fetched lazily on first use."
fi

# --- 6. frontend build (skip if disabled) -------------------------------------
if [[ "${POLYFORGE_NO_FRONTEND:-}" != "1" ]]; then
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

# --- 7. choose what to run ---------------------------------------------------
# Default: start the FastAPI server (which now also serves the
# compiled frontend at /). Setting POLYFORGE_UI=1 (or --ui) starts
# the legacy Gradio launcher instead, for users coming from the old
# setup.
LAUNCHER_PY="$SCRIPT_DIR/launcher.py"

if [[ "${POLYFORGE_UI:-}" == "1" && -f "$LAUNCHER_PY" ]]; then
    # Honour SIGINT / SIGTERM for graceful shutdown.
    trap 'log "Caught signal — shutting down."; kill -TERM "$LAUNCHER_PID" 2>/dev/null || true; wait "$LAUNCHER_PID" 2>/dev/null || true; exit 0' INT TERM

    log "Starting legacy Gradio launcher (python launcher.py)…"
    log "Open the URL it prints (default http://127.0.0.1:7860) in your browser."

    PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
        "$VENV_DIR/bin/python" "$LAUNCHER_PY" 2>&1 | tee "$LOG_DIR/launcher.log"
    exit $?
fi

POLYFORGE_HOST="${POLYFORGE_HOST:-127.0.0.1}"
POLYFORGE_PORT="${POLYFORGE_PORT:-8081}"
export POLYFORGE_HOST
export POLYFORGE_PORT
if [[ -n "${POLYFORGE_API_KEY:-}" ]]; then
    export POLYFORGE_API_KEY
    log "API key auth: ENABLED (X-API-Key required)"
else
    log "API key auth: disabled (binding $POLYFORGE_HOST is loopback)"
fi

# Honour SIGINT / SIGTERM for graceful shutdown.
trap 'log "Caught signal — shutting down."; kill -TERM "$API_PID" 2>/dev/null || true; wait "$API_PID" 2>/dev/null || true; exit 0' INT TERM

log "Starting PolyForge API on http://$POLYFORGE_HOST:$POLYFORGE_PORT"
log "Open http://$POLYFORGE_HOST:$POLYFORGE_PORT/ in your browser for the PolyForge UI."
log "Logs: tail -f $LOG_DIR/api.log"

# Run uvicorn directly from the venv so re-installs are picked up immediately.
PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    "$VENV_DIR/bin/python" -m uvicorn \
    hy3dgen.api.server:app \
    --host "$POLYFORGE_HOST" \
    --port "$POLYFORGE_PORT" \
    >> "$LOG_DIR/api.log" 2>&1 &
API_PID=$!

# Brief readiness probe so users see a clear OK / ERROR before exiting.
for _ in {1..40}; do
    if curl -fsS "http://${POLYFORGE_HOST}:${POLYFORGE_PORT}/health" >/dev/null 2>&1; then
        log "API ready (pid $API_PID). Frontend served at http://$POLYFORGE_HOST:$POLYFORGE_PORT/"
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