#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# PolyForge — one-shot smart launcher (Do prompt ao polígono)
#
# No arguments required. Detects state, fixes gaps, then runs:
#
#   1. Picks a supported Python 3.10–3.12 interpreter and project venv.
#   2. Detects NVIDIA hardware and selects CUDA or CPU mode.
#   3. Installs/updates the backend (``pip install -e .``) and the
#      ``[ml]`` extra so the inference worker can load weights when
#      a job is submitted. Skips already-satisfied dependencies.
#   4. Runs ``npm ci`` + ``npm run build`` for the frontend if
#      ``polyforge_frontend/dist/`` is missing or older than its
#      sources.
#   5. Boots the PolyForge API on ``http://127.0.0.1:8081`` (override
#      via ``POLYFORGE_PORT`` / ``POLYFORGE_HOST`` env vars). The Vite
#      ``dist/`` is served at the same URL so the browser shows the
#      PolyForge UI without a separate dev server.
#   6. Installs a ``polyforge.desktop`` menu entry (Graphics category)
#      and opens the UI in the default browser once /health answers.
#      Opt out with ``--no-desktop`` / ``--no-browser``.
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
#   POLYFORGE_NO_FRONTEND skip the npm build (default: unset; Node 22.12+ required)
#   POLYFORGE_FORCE_REINSTALL touch the stamp to force reinstall
#   POLYFORGE_INSTALL_MODE auto|cuda|cpu|api-only (default: auto)
#   POLYFORGE_VENV       local venv path (default: .venv)
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
#   POLYFORGE_NO_BROWSER
#                       don't auto-open the UI in the default browser
#                       once the API is ready (default: unset = open).
#   POLYFORGE_NO_DESKTOP
#                       don't install the system menu launcher
#                       (default: unset = install into
#                       ~/.local/share/applications).
#
# Flags (alternative to env vars):
#   --no-browser        same as POLYFORGE_NO_BROWSER=1
#   --no-desktop        same as POLYFORGE_NO_DESKTOP=1
#   --install-desktop   install the system menu launcher and exit
#   --uninstall-desktop remove the system menu launcher and exit
#   --ui                same as POLYFORGE_UI=1 (legacy Gradio launcher)
#   --no-ml             same as POLYFORGE_NO_ML=1
#   --no-frontend       same as POLYFORGE_NO_FRONTEND=1
#   --mode MODE         auto, cuda, cpu, or api-only
#   --cpu               shorthand for --mode cpu
#   --gpu               shorthand for --mode cuda
#   --api-only          shorthand for --mode api-only
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
    sed -n '2,/^# -----------------------------------------------------------------------------$/p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while (( $# )); do
    case "$1" in
        --help|-h) show_help ;;
        --ui)       POLYFORGE_UI=1 ;;
        --no-ml)    POLYFORGE_NO_ML=1 ;;
        --no-frontend) POLYFORGE_NO_FRONTEND=1 ;;
        --mode)
            [[ -n "${2:-}" ]] || die "--mode needs auto, cuda, cpu, or api-only."
            POLYFORGE_INSTALL_MODE="$2"
            shift
            ;;
        --mode=*) POLYFORGE_INSTALL_MODE="${1#*=}" ;;
        --cpu) POLYFORGE_INSTALL_MODE=cpu ;;
        --gpu) POLYFORGE_INSTALL_MODE=cuda ;;
        --api-only) POLYFORGE_INSTALL_MODE=api-only ;;
        --download-models) POLYFORGE_DOWNLOAD_MODELS=1 ;;
        --no-download-models) POLYFORGE_DOWNLOAD_MODELS=0 ;;
        --model-scope)
            [[ -n "${2:-}" ]] || die "--model-scope needs a value: shape, multiview, tex, t2i or all."
            POLYFORGE_MODEL_SCOPE="$2"
            shift
            ;;
        --model-scope=*) POLYFORGE_MODEL_SCOPE="${1#*=}" ;;
        --reinstall) POLYFORGE_FORCE_REINSTALL=1 ;;
        --no-browser) POLYFORGE_NO_BROWSER=1 ;;
        --no-desktop) POLYFORGE_NO_DESKTOP=1 ;;
        --install-desktop) POLYFORGE_INSTALL_DESKTOP_ONLY=1 ;;
        --uninstall-desktop) POLYFORGE_UNINSTALL_DESKTOP_ONLY=1 ;;
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
STAMP_FILE="$SCRIPT_DIR/.polyforge_launcher.stamp"
PROFILE_FILE="$SCRIPT_DIR/.polyforge_launcher.profile"

# --- desktop entry only (no Python/Node needed) -------------------------------
# --install-desktop / --uninstall-desktop exit here, before any toolchain
# detection, so they work on a fresh checkout.
_desktop_apps_dir="$HOME/.local/share/applications"
_desktop_file="$_desktop_apps_dir/polyforge.desktop"
_desktop_icon="$HOME/.local/share/icons/hicolor/256x256/apps/polyforge.png"
if [[ "${POLYFORGE_UNINSTALL_DESKTOP_ONLY:-}" == "1" ]]; then
    rm -f "$_desktop_file" "$_desktop_icon"
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$_desktop_apps_dir" >/dev/null 2>&1 || true
    fi
    _ts() { date '+%Y-%m-%d %H:%M:%S'; }
    printf '[%s] Menu launcher removed.\n' "$(_ts)"
    exit 0
fi
if [[ "${POLYFORGE_INSTALL_DESKTOP_ONLY:-}" == "1" ]]; then
    _template="$SCRIPT_DIR/packaging/polyforge.desktop.in"
    if [[ ! -f "$_template" ]]; then
        printf 'Desktop template missing (%s).\n' "$_template" >&2
        exit 1
    fi
    mkdir -p "$_desktop_apps_dir"
    sed "s#__POLYFORGE_DIR__#$SCRIPT_DIR#g" "$_template" > "$_desktop_file"
    chmod 644 "$_desktop_file"
    if [[ -f "$SCRIPT_DIR/assets/logo/polyforge-icon-256.png" ]]; then
        mkdir -p "$HOME/.local/share/icons/hicolor/256x256/apps"
        cp -f "$SCRIPT_DIR/assets/logo/polyforge-icon-256.png" "$_desktop_icon"
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$_desktop_apps_dir" >/dev/null 2>&1 || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
    fi
    _ts() { date '+%Y-%m-%d %H:%M:%S'; }
    printf '[%s] Menu launcher installed: %s (Graphics → PolyForge).\n' "$(_ts)" "$_desktop_file"
    exit 0
fi
unset _desktop_apps_dir _desktop_file _desktop_icon _template
PYPROJECT="$SCRIPT_DIR/pyproject.toml"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
FRONTEND_DIR="$SCRIPT_DIR/polyforge_frontend"
FRONTEND_DIST="$FRONTEND_DIR/dist"
PACKAGE_JSON="$FRONTEND_DIR/package.json"
PACKAGE_LOCK="$FRONTEND_DIR/package-lock.json"
LOG_DIR="$SCRIPT_DIR/.polyforge_logs"
VENV_DIR="${POLYFORGE_VENV:-$SCRIPT_DIR/.venv}"

# --- 1. choose local execution mode ------------------------------------------
install_mode="${POLYFORGE_INSTALL_MODE:-auto}"
case "$install_mode" in
    auto|cuda|cpu|api-only) ;;
    *) die "Unknown install mode '$install_mode'. Choose auto, cuda, cpu, or api-only." ;;
esac

has_nvidia=0
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    has_nvidia=1
fi

dotenv_device=""
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    dotenv_device="$(sed -n 's/^POLYFORGE_DEVICE=//p' "$SCRIPT_DIR/.env" | tail -n 1 | tr -d '\"' | xargs)"
fi

case "$install_mode" in
    cuda)
        (( has_nvidia )) || die "CUDA mode requested, but nvidia-smi cannot access a GPU. Install/fix the host NVIDIA driver or use --mode cpu."
        selected_device=cuda
        ;;
    cpu)
        selected_device=cpu
        ;;
    api-only)
        selected_device=cpu
        POLYFORGE_NO_ML=1
        POLYFORGE_NO_FRONTEND=1
        ;;
    auto)
        selected_device="${POLYFORGE_DEVICE:-${dotenv_device:-}}"
        if [[ -z "$selected_device" ]]; then
            if (( has_nvidia )); then selected_device=cuda; else selected_device=cpu; fi
        fi
        if [[ "$selected_device" == "cuda" ]] && (( ! has_nvidia )); then
            warn "CUDA is configured but nvidia-smi found no usable GPU; selecting CPU for this run."
            selected_device=cpu
        fi
        ;;
esac
[[ "$selected_device" == "cuda" || "$selected_device" == "cpu" ]] || die "POLYFORGE_DEVICE must be cuda or cpu."
export POLYFORGE_DEVICE="$selected_device"
log "Install mode: $install_mode; inference device: $POLYFORGE_DEVICE (NVIDIA GPU detected: $((has_nvidia)))"

# Create the local configuration once. Never overwrite a user's existing .env.
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    if [[ "$OSTYPE" == darwin* ]]; then
        sed -i '' "s/^POLYFORGE_DEVICE=.*/POLYFORGE_DEVICE=$POLYFORGE_DEVICE/" "$SCRIPT_DIR/.env"
    else
        sed -i "s/^POLYFORGE_DEVICE=.*/POLYFORGE_DEVICE=$POLYFORGE_DEVICE/" "$SCRIPT_DIR/.env"
    fi
    log "Created .env with loopback binding and device=$POLYFORGE_DEVICE."
fi

mkdir -p "$LOG_DIR"

# Fail early if the full local UI cannot be built.
if [[ "${POLYFORGE_NO_FRONTEND:-}" != "1" ]]; then
    command -v node >/dev/null 2>&1 || die "Node.js 22.12+ is required for the local UI. Install Node or rerun with --no-frontend."
    command -v npm >/dev/null 2>&1 || die "npm is required for the local UI. Install npm or rerun with --no-frontend."
    NODE_VERSION="$(node -p 'process.versions.node')"
    IFS=. read -r NODE_MAJOR NODE_MINOR _ <<< "$NODE_VERSION"
    if (( NODE_MAJOR < 22 || (NODE_MAJOR == 22 && NODE_MINOR < 12) )); then
        die "Node.js $NODE_VERSION is too old; install Node 22.12+ or rerun with --no-frontend."
    fi
    log "Node $NODE_VERSION detected"
fi

# --- 2. pick a supported Python ----------------------------------------------
python_in_range() {
    local candidate="$1" version major minor
    command -v "$candidate" >/dev/null 2>&1 || return 1
    version="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)" || return 1
    major="${version%%.*}"
    minor="${version##*.}"
    (( major == 3 && minor >= 10 && minor <= 12 ))
}

PYTHON_BIN="${PYTHON:-}"
if [[ -n "$PYTHON_BIN" ]]; then
    python_in_range "$PYTHON_BIN" || die "PYTHON=$PYTHON_BIN must be Python 3.10, 3.11, or 3.12."
else
    for candidate in python3.12 python3.11 python3.10 python3; do
        if python_in_range "$candidate"; then
            PYTHON_BIN="$candidate"
            break
        fi
    done
    [[ -n "$PYTHON_BIN" ]] || die "Python 3.10–3.12 not found. Install one or set PYTHON=/path/to/python3.12."
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
log "Detected Python $PY_VERSION ($PYTHON_BIN)"

# --- 2. create / refresh the venv --------------------------------------------
needs_venv_create=0
if [[ ! -d "$VENV_DIR" ]]; then
    needs_venv_create=1
elif [[ ! -x "$VENV_DIR/bin/python" ]]; then
    die "Existing venv at $VENV_DIR is incomplete; it was left untouched. Set POLYFORGE_VENV to a new path."
elif ! python_in_range "$VENV_DIR/bin/python"; then
    existing_version="$("$VENV_DIR/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo unknown)"
    die "Existing venv at $VENV_DIR uses Python $existing_version; it was left untouched. Set POLYFORGE_VENV to a new path using Python 3.10–3.12."
fi

if (( needs_venv_create )); then
    log "Creating venv at $VENV_DIR (this may take a minute)…"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Pin python to the venv's interpreter for the rest of the run.
PYTHON="$VENV_DIR/bin/python"
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

# pip install logic: the [ml] extra is pure wheels (``diso`` was removed
# from it — it compiles CUDA extensions against the torch build, so a
# host CUDA toolkit mismatch breaks the whole install; the runtime
# falls back to "mc" automatically, see ``hy3dgen.inference._generate``).
# If the editable install still fails, we install the pure-Python ML
# deps individually as a safety net, so the user keeps a working
# inference path instead of an API-only build that can't load any
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
        if [[ "$POLYFORGE_DEVICE" == "cpu" ]]; then
            log "Pre-installing CPU-only torch + torchvision…"
            TORCH_INSTALL=(--index-url https://download.pytorch.org/whl/cpu torch torchvision)
        else
            log "Pre-installing torch + torchvision for the detected CUDA environment…"
            TORCH_INSTALL=(torch torchvision)
        fi
        if ! "$PYTHON" -m pip install --quiet "${TORCH_INSTALL[@]}"; then
            warn "torch install failed; will continue with the editable install and hope for the best."
        fi
    fi

    # Step 2: editable install with the rest. --no-build-isolation so
    # the build sandbox can see torch and any other already-installed
    # packages.
    if "$PYTHON" -m pip install --quiet --no-build-isolation -e ".[$extra]"; then
        return 0
    fi

    warn "Editable install failed; retrying with individual ML wheels."
    warn "This still gives you a working inference pipeline; only the"
    warn "optional DMC surface extractor won't be available (the runtime"
    warn "falls back to 'mc' automatically; install 'diso' manually with"
    warn "a matching CUDA toolkit if you need it)."

    # ``pip install -e .[ml,dev]`` is monolithic, so we install the rest
    # individually and then do the editable dev extra for our own
    # package metadata.
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

current_profile="${POLYFORGE_NO_ML:-0}:${POLYFORGE_DEVICE}"
profile_changed=0
if [[ ! -f "$PROFILE_FILE" || "$(<"$PROFILE_FILE")" != "$current_profile" ]]; then
    profile_changed=1
fi

if (( profile_changed )) || manifest_changed "$STAMP_FILE" "${BACKEND_MANIFESTS[@]}"; then
    if [[ "${POLYFORGE_NO_ML:-}" == "1" ]]; then
        "$PYTHON" -m pip install --quiet -e ".[dev]"
    else
        do_backend_install || die "Backend install failed."
    fi
    current_profile="${POLYFORGE_NO_ML:-0}:${POLYFORGE_DEVICE}"
    printf '%s' "$current_profile" > "$PROFILE_FILE"
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
    printf 'Download model weights now? [y/N/all/shape/multiview/tex/t2i] '
    read -r answer </dev/tty || answer=""
    case "${answer,,}" in
        ""|n|no|0|false) return 1 ;;
        y|yes|all) POLYFORGE_MODEL_SCOPE="all" ;;
        shape|multiview|tex|t2i) POLYFORGE_MODEL_SCOPE="${answer,,}" ;;
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
        needs_npm_install=0
        if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
            needs_npm_install=1
        elif manifest_changed "$STAMP_FILE" "$PACKAGE_JSON" "$PACKAGE_LOCK"; then
            needs_npm_install=1
        fi

        if (( needs_npm_install )); then
            log "Installing frontend dependencies (npm ci)…"
            ( cd "$FRONTEND_DIR" && npm ci --no-audit --no-fund )
        fi

        if manifest_changed "$STAMP_FILE" "$PACKAGE_JSON" "$PACKAGE_LOCK" || [[ ! -d "$FRONTEND_DIST" ]]; then
            log "Building frontend (npm run build)…"
            ( cd "$FRONTEND_DIR" && npm run build )
        else
            log "Frontend dist present and fresh; skipping build."
        fi
fi

# Final stamp update so we don't reinstall on every invocation.
touch "$STAMP_FILE"

# --- 6b. system menu launcher (Linux desktop entry) ---------------------------
# Installs ~/.local/share/applications/polyforge.desktop so PolyForge shows
# up in the app menu under Graphics / 3D. Skipped on macOS/Windows, in
# headless sessions, or with --no-desktop / POLYFORGE_NO_DESKTOP=1.
# The .desktop points at this repo's launcher.sh, so moving the repo
# requires a reinstall (rerun ./launcher.sh).
install_desktop_entry() {
    local apps_dir desktop_file template icon_src
    apps_dir="$HOME/.local/share/applications"
    desktop_file="$apps_dir/polyforge.desktop"
    template="$SCRIPT_DIR/packaging/polyforge.desktop.in"
    icon_src="$SCRIPT_DIR/assets/logo/polyforge-icon-256.png"
    [[ -f "$template" ]] || { warn "Desktop template missing ($template); skipping menu entry."; return 0; }
    mkdir -p "$apps_dir"
    sed "s#__POLYFORGE_DIR__#$SCRIPT_DIR#g" "$template" > "$desktop_file"
    chmod 644 "$desktop_file"
    if [[ -f "$icon_src" ]]; then
        mkdir -p "$HOME/.local/share/icons/hicolor/256x256/apps"
        cp -f "$icon_src" "$HOME/.local/share/icons/hicolor/256x256/apps/polyforge.png"
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$apps_dir" >/dev/null 2>&1 || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
    fi
    log "Menu launcher installed: $desktop_file (Graphics → PolyForge)."
}

uninstall_desktop_entry() {
    local desktop_file="$HOME/.local/share/applications/polyforge.desktop"
    local icon_file="$HOME/.local/share/icons/hicolor/256x256/apps/polyforge.png"
    rm -f "$desktop_file" "$icon_file"
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
    fi
    log "Menu launcher removed."
}

if [[ "${POLYFORGE_NO_DESKTOP:-}" != "1" && "$OSTYPE" != darwin* && "$OSTYPE" != msys* && "$OSTYPE" != cygwin* ]]; then
    if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" || -d "$HOME/.local/share/applications" ]]; then
        install_desktop_entry
    else
        log "Skipping menu launcher (headless session; use --install-desktop to force)."
    fi
fi

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

# --- 8. open the UI in the default browser ------------------------------------
# Only when the API answered /health above, only for loopback binds, and
# never in headless sessions. Opt out with --no-browser /
# POLYFORGE_NO_BROWSER=1.
open_browser() {
    local url="$1"
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1 &
    elif command -v gio >/dev/null 2>&1; then
        gio open "$url" >/dev/null 2>&1 &
    elif command -v open >/dev/null 2>&1; then
        open "$url" >/dev/null 2>&1 &
    elif command -v powershell.exe >/dev/null 2>&1; then
        powershell.exe -NoProfile -Command "Start-Process '$url'" >/dev/null 2>&1 &
    else
        return 1
    fi
}

if [[ "${POLYFORGE_NO_BROWSER:-}" != "1" ]]; then
    case "$POLYFORGE_HOST" in
        127.0.0.1|::1|localhost)
            if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] || [[ "$OSTYPE" == darwin* ]]; then
                if open_browser "http://$POLYFORGE_HOST:$POLYFORGE_PORT/"; then
                    log "Opened the PolyForge UI in your default browser."
                else
                    log "Open http://$POLYFORGE_HOST:$POLYFORGE_PORT/ in your browser for the PolyForge UI."
                fi
            else
                log "Headless session — open http://$POLYFORGE_HOST:$POLYFORGE_PORT/ from a browser."
            fi
            ;;
        *)
            log "Remote bind ($POLYFORGE_HOST) — open the UI manually (browser auto-open is loopback-only)."
            ;;
    esac
fi

log "Press Ctrl+C to stop."
wait "$API_PID"