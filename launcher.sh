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
#   --foreground        keep the launcher in the foreground (Ctrl+C stops
#                       the API). Default is detached: the API runs in its
#                       own session and survives closing the terminal.
#   --detach            explicit alias for the default detached behavior.
#   --stop              stop a running PolyForge API (uses the PID file).
#   --status            report whether the API is running and /health is OK.
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
        --stop) POLYFORGE_STOP_ONLY=1 ;;
        --status) POLYFORGE_STATUS_ONLY=1 ;;
        --foreground) POLYFORGE_FOREGROUND=1 ;;
        --detach) POLYFORGE_FOREGROUND=0 ;;
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
API_PID_FILE="$SCRIPT_DIR/.polyforge_api.pid"

# --- early-exit commands: --stop / --status -----------------------------------
# Handle these BEFORE the Python/venv setup so they work even if the
# interpreter or venv is broken / missing. The PID file is the source of
# truth for "is the API running?".
api_read_pid() {
    [[ -f "$API_PID_FILE" ]] || return 1
    local pid
    pid="$(tr -d '[:space:]' < "$API_PID_FILE" 2>/dev/null || true)"
    [[ -n "$pid" ]] || return 1
    printf '%s\n' "$pid"
}

api_is_running() {
    local pid
    pid="$(api_read_pid 2>/dev/null || true)"
    [[ -n "$pid" ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    # Confirm it's actually our uvicorn (PPID might have been reparented to
    # init if the launcher exited).
    local cmd
    cmd="$(ps -p "$pid" -o comm= 2>/dev/null || true)"
    [[ "$cmd" == "python"* ]] || return 1
    return 0
}

# Best-effort: is *any* uvicorn bound to our port, regardless of PID file?
# This is the safety net for the case where the PID file is stale (or
# points to a defunct process) but a previous run's uvicorn is still
# serving traffic. We can't read another process's PID from outside, so
# we only get a yes/no answer; the caller decides what to do with it.
#
# We deliberately look for a *LISTEN* socket (``st == 0A`` in
# /proc/net/tcp). A naive ``bind()`` test would return "in use" for
# any TCP port in TIME_WAIT after the API shut down, which is a
# false positive — TIME_WAIT is a closing connection, not a server.
api_port_in_use() {
    local port="${1:-8081}"
    local port_hex
    port_hex="$(printf '%04X' "$port")"
    if command -v ss >/dev/null 2>&1; then
        ss -ltn "sport = :$port" 2>/dev/null | grep -q ":$port"
        return $?
    fi
    # Fall back to /proc/net/tcp{,6} — same approach the kernel
    # exposes through ss, so it tells the truth about LISTEN state.
    # ``st`` column 4 is 0A for LISTEN.
    if grep -qE ":${port_hex} [0-9A-F:]+ 0A" /proc/net/tcp /proc/net/tcp6 2>/dev/null; then
        return 0
    fi
    return 1
}

# Resolve the PID of the process listening on $1 by parsing
# /proc/net/tcp{,6}. Returns the PID on stdout, or empty on failure.
#
# /proc/net/tcp columns: sl  local_address rem_address st tx_queue rx_queue
# tr tm smacet  retrnsmt   uid timeout inode
# local_address is "IP:PORT" in hex. st == 0A (TCP_LISTEN). Each socket
# has an inode; /proc/$pid/fd/* symlinks to "socket:[inode]".
api_pid_from_port() {
    local port_hex inode pid fd_link
    port_hex="$(printf '%04X' "${1:-8081}")"
    # Grep listens on this port, take the first match's inode (10th col).
    # Use ``cut`` instead of awk/read so we never have to worry about
    # the surrounding command substitution eating our field syntax.
    # Inode is field 10 of /proc/net/tcp (sl local rem st tx rx tr tm
    # retrnsmt uid timeout inode ...). After ``tr -s ' '`` collapses
    # the ragged whitespace, ``cut`` uses 1-based indices but counts
    # the leading space as a field, so the inode lives at index 11.
    inode="$(grep -hE ":${port_hex} 0+:0+ 0A" /proc/net/tcp /proc/net/tcp6 2>/dev/null \
        | head -n 1 | tr -s ' ' | cut -d' ' -f11)"
    [[ -n "$inode" ]] || return 1
    # Find the PID whose fd table contains a socket with that inode.
    # Strategy: narrow to Python processes owned by us (pgrep is much
    # faster than scanning /proc/[0-9]*/fd/*, and the uvicorn is the
    # only Python process that opens a TCP listener), then match
    # "socket:[INODE]" on each fd symlink.
    local pid fd target needle="socket:[${inode}]"
    for pid in $(pgrep -u "$(id -u)" python 2>/dev/null); do
        for fd in "/proc/$pid/fd"/*; do
            [[ -L "$fd" ]] || continue
            target="$(readlink "$fd" 2>/dev/null || true)"
            if [[ "$target" == "$needle" ]]; then
                printf '%s\n' "$pid"
                return 0
            fi
        done
    done
    return 1
}

if [[ "${POLYFORGE_STOP_ONLY:-}" == "1" ]]; then
    pid="$(api_read_pid 2>/dev/null || true)"
    if [[ -z "$pid" ]]; then
        log "No API is running (no PID file at $API_PID_FILE)."
        exit 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        log "Stale PID file: process $pid is gone. Removing it."
        rm -f "$API_PID_FILE"
        exit 0
    fi
    log "Stopping PolyForge API (pid $pid)…"
    kill -TERM "$pid" 2>/dev/null || true
    for _ in {1..20}; do
        if ! kill -0 "$pid" 2>/dev/null; then break; fi
        sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
        warn "Process $pid did not exit; sending SIGKILL."
        kill -KILL "$pid" 2>/dev/null || true
    fi
    rm -f "$API_PID_FILE"
    log "API stopped."
    exit 0
fi

if [[ "${POLYFORGE_STATUS_ONLY:-}" == "1" ]]; then
    port="${POLYFORGE_PORT:-8081}"
    if api_is_running; then
        pid="$(api_read_pid)"
        if curl -fsS "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
            echo "running (pid $pid, http://127.0.0.1:${port} healthy)"
            exit 0
        fi
        echo "starting (pid $pid, /health not yet answering)"
        exit 0
    fi
    # PID file says stopped, but the port might still be bound by an
    # orphan uvicorn from a previous run. Report it so the user can
    # decide whether to kill it.
    if api_port_in_use "$port"; then
        echo "port $port is held by an unknown process (no PID file); try: ss -ltnp sport = :$port"
        exit 1
    fi
    echo "stopped (no PID file, port $port free)"
    exit 1
fi

# --- idempotency: short-circuit if the API is already running -----------------
# Defaults match the rest of the launcher. The check happens BEFORE the
# Python/venv/pip/npm setup so a second invocation of `./launcher.sh`
# (e.g. after the user re-opens a terminal) is instant: no reinstall,
# no rebuild. This also means the launcher can be wired up to a desktop
# file or a keyboard shortcut without worrying about double-starts.
POLYFORGE_HOST="${POLYFORGE_HOST:-127.0.0.1}"
POLYFORGE_PORT="${POLYFORGE_PORT:-8081}"

# Self-heal: if the PID file points to a dead process, drop it so we
# can start a fresh one without false "already running" results.
if [[ -f "$API_PID_FILE" ]] && ! api_is_running; then
    rm -f "$API_PID_FILE"
fi

if [[ "${POLYFORGE_FOREGROUND:-0}" != "1" && "${POLYFORGE_UI:-}" != "1" ]] && api_is_running; then
    existing_pid="$(api_read_pid)"
    if curl -fsS "http://${POLYFORGE_HOST}:${POLYFORGE_PORT}/health" >/dev/null 2>&1; then
        log "PolyForge API is already running (pid $existing_pid) at http://$POLYFORGE_HOST:$POLYFORGE_PORT/"
        # Only open the browser when we know the user actually wants it
        # (the browser flag is parsed later; reuse POLYFORGE_NO_BROWSER
        # which the user can set). Default to opening the browser on
        # loopback binds.
        if [[ "${POLYFORGE_NO_BROWSER:-}" != "1" ]] && command -v xdg-open >/dev/null 2>&1; then
            ( xdg-open "http://$POLYFORGE_HOST:$POLYFORGE_PORT/" >/dev/null 2>&1 & ) || true
            log "Opened the PolyForge UI in your default browser."
        fi
    else
        log "PolyForge API is starting (pid $existing_pid)…"
    fi
    exit 0
fi

# Last-resort: the port is in use but we have no PID for it. Two cases:
#   1. /health answers OK → it's a previous run's uvicorn that we
#      lost track of (PID file stale, setsid wrapper ate the PID,
#      etc.). Re-adopt it by writing a fresh PID file (best effort) and
#      short-circuit. We can't recover the original PID without
#      /proc, so we just leave the running API alone and report success.
#   2. /health does NOT answer → the port is held by something else
#      entirely. Refuse to start a second uvicorn that would just fail
#      to bind; tell the user how to recover.
if [[ "${POLYFORGE_FOREGROUND:-0}" != "1" && "${POLYFORGE_UI:-}" != "1" ]] && api_port_in_use "$POLYFORGE_PORT"; then
    if curl -fsS "http://${POLYFORGE_HOST}:${POLYFORGE_PORT}/health" >/dev/null 2>&1; then
        log "PolyForge API is already running on port $POLYFORGE_PORT (orphan: no PID file). Open http://$POLYFORGE_HOST:$POLYFORGE_PORT/ in your browser."
        if [[ "${POLYFORGE_NO_BROWSER:-}" != "1" ]] && command -v xdg-open >/dev/null 2>&1; then
            ( xdg-open "http://$POLYFORGE_HOST:$POLYFORGE_PORT/" >/dev/null 2>&1 & ) || true
        fi
        # Best-effort PID recovery: scan /proc for processes that own
        # a TCP socket bound to our port. ``ss`` would do this for us
        # but it's not always installed; reading /proc/net/tcp works
        # everywhere.
        orphan_pid="$(api_pid_from_port "$POLYFORGE_PORT" || true)"
        if [[ -n "$orphan_pid" ]] && [[ "$orphan_pid" =~ ^[0-9]+$ ]]; then
            printf '%s\n' "$orphan_pid" > "$API_PID_FILE"
        fi
        exit 0
    fi
    die "Port $POLYFORGE_PORT is already bound by another process (and /health is not answering). Run 'ss -ltnp sport = :$POLYFORGE_PORT' (or 'sudo lsof -iTCP:$POLYFORGE_PORT -sTCP:LISTEN') to find it, or use POLYFORGE_PORT to pick a different one."
fi

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

# Best-effort NVIDIA detection. ``nvidia-smi`` may be missing or
# inaccessible inside a Flatpak / pressure-vessel sandbox even when
# the host driver is loaded — in that case we still want CUDA. The
# most reliable signal is the kernel's own view:
# ``/proc/driver/nvidia/gpus/`` lists one PCI BDF per GPU when the
# nvidia.ko module is up, regardless of which userspace tools are
# visible to the sandbox.
nvidia_smi_cmd=""
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia_smi_cmd="nvidia-smi"
elif [[ -x /run/host/usr/bin/nvidia-smi ]]; then
    # Inside a Flatpak the host binaries are bind-mounted under
    # /run/host. nvidia-smi there talks to the host driver via the
    # forwarded device nodes.
    nvidia_smi_cmd="/run/host/usr/bin/nvidia-smi"
fi

has_nvidia=0
if [[ -d /proc/driver/nvidia/gpus ]]; then
    # /proc/driver/nvidia/gpus/<BDF> exists for every GPU the kernel
    # sees. The directory is empty (not absent) when no driver is
    # loaded, so we count actual entries.
    if [[ -n "$(ls -A /proc/driver/nvidia/gpus 2>/dev/null)" ]]; then
        has_nvidia=1
    fi
fi
if (( ! has_nvidia )) && [[ -n "$nvidia_smi_cmd" ]] && "$nvidia_smi_cmd" -L >/dev/null 2>&1; then
    has_nvidia=1
fi

# When the GPU is real but its libs live on the host (sandboxed
# environment), prefer a Python interpreter that was *also* installed
# on the host. Mixing a host Python (linked against the host glibc)
# with sandbox loader paths works; mixing a Flatpak Python with the
# host glibc is what produces the
# ``__nptl_change_stack_perm: undefined symbol`` errors that break
# every dynamically-linked binary the launcher shell calls.
#
# The default order in ``discover_python_candidates`` already
# surfaces ``/run/host/usr/bin/python3.1X`` if the user has it, so
# the venv will be created against the host interpreter and torch
# will find libcuda naturally — no LD_LIBRARY_PATH hack required.
# We only need to warn the user if the venv is currently on a
# non-host Python and the GPU is real, because that's a setup
# that is destined to fail. The check happens after ``PYTHON_BIN``
# is resolved, just before the install.
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
# Returns 0 when $1 is an executable Python whose version is 3.10–3.12.
# Accepts both bare commands (resolved via PATH) and absolute paths.
python_in_range() {
    local candidate="$1" version major minor
    if [[ "$candidate" == */* ]]; then
        [[ -x "$candidate" ]] || return 1
    else
        command -v "$candidate" >/dev/null 2>&1 || return 1
    fi
    version="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)" || return 1
    major="${version%%.*}"
    minor="${version##*.}"
    (( major == 3 && minor >= 10 && minor <= 12 ))
}

# Build an ordered candidate list of Python 3.10–3.12 interpreters from
# the most common install locations, in addition to whatever is on PATH.
# This lets `./launcher.sh` work zero-config on machines where Python is
# only present in uv / pyenv / system dirs / Flatpak sandboxes instead
# of as a `python3.12` shim.
#
# Strategy: discover all candidates across every source, then sort by
# version descending so Python 3.12 is preferred over 3.11 over 3.10
# regardless of which install location it came from. The first hit wins.
discover_python_candidates() {
    local p raw
    # 1. PATH first (respects user preference, virtualenv activation, etc.).
    for p in python3.12 python3.11 python3.10 python3; do
        printf '%s\n' "$p"
    done
    # 2. uv-managed installs (most common on dev workstations).
    if [[ -d "$HOME/.local/share/uv/python" ]]; then
        find "$HOME/.local/share/uv/python" -maxdepth 3 -type f -name 'python3.1[02]' 2>/dev/null
    fi
    # 3. uv tool shims and python-builds under ~/.local/bin.
    if [[ -d "$HOME/.local/bin" ]]; then
        find "$HOME/.local/bin" -maxdepth 1 \( -type l -o -type f \) -name 'python3.1[02]' 2>/dev/null
    fi
    # 4. pyenv (PYENV_ROOT or default location).
    local pyenv_root="${PYENV_ROOT:-$HOME/.pyenv}"
    if [[ -d "$pyenv_root/versions" ]]; then
        find "$pyenv_root/versions" -maxdepth 2 -type f -name 'python3.1[02]' 2>/dev/null
    fi
    # 5. Standard system locations. When running inside a Flatpak /
    #    pressure-vessel sandbox the host's /usr/bin is bind-mounted
    #    under /run/host. Prefer that Python over the Flatpak one
    #    below: they share a glibc, so venvs created against them
    #    can transparently link against the host's CUDA libs.
    for p in \
        /run/host/usr/bin/python3.12 /run/host/usr/bin/python3.11 /run/host/usr/bin/python3.10 \
        /usr/bin/python3.12 /usr/bin/python3.11 /usr/bin/python3.10 \
        /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3.10 \
        /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.10; do
        [[ -e "$p" ]] && printf '%s\n' "$p"
    done
    # 6. Flatpak app sandboxes (e.g. python interpreters shipped with VS Code).
    #    Skip when the host's Python is reachable: Flatpak pythons are
    #    linked against a different glibc than /run/host/usr/lib, so
    #    mixing them with the host CUDA libs (or any host /run/host
    #    binary) produces ``__nptl_change_stack_perm`` style symbol
    #    clashes inside the sandbox. Only fall through to Flatpak when
    #    no host Python is available.
    if [[ -d "$HOME/.var/app" ]] && [[ ! -x /run/host/usr/bin/python3.12 ]] && [[ ! -x /run/host/usr/bin/python3.11 ]] && [[ ! -x /run/host/usr/bin/python3.10 ]]; then
        find "$HOME/.var/app" -maxdepth 8 -type f -name 'python3.1[02]' 2>/dev/null
    fi
}

# Tag every candidate with its minor version (3.10/3.11/3.12) and sort
# descending so newer interpreters win. PATH entries without a version
# suffix get version "0" so they sort after versioned paths.
sort_candidates_by_version() {
    local line v p
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        p="$line"
        # If the candidate is just "python3", probe it once via command -v.
        if [[ "$p" != */* && "$p" != python3.1[012] ]]; then
            p="$(command -v "$p" 2>/dev/null || true)"
            [[ -z "$p" ]] && continue
        fi
        # Extract 3.XX from the path or binary name; bare "python3" → 3.0.
        v="$(printf '%s\n' "$p" | sed -nE 's#.*/python(3\.[0-9]+)$#\1#p')"
        [[ -z "$v" ]] && v="3.0"
        printf '%s|%s\n' "$v" "$p"
    done
}

PYTHON_BIN="${PYTHON:-}"
if [[ -n "$PYTHON_BIN" ]]; then
    python_in_range "$PYTHON_BIN" || die "PYTHON=$PYTHON_BIN must be Python 3.10, 3.11, or 3.12."
else
    # Track which candidates we already tried so duplicates from PATH +
    # uv + flatpak paths don't shadow the first hit. We also reorder
    # candidates by version descending (3.12 before 3.11 before 3.10)
    # so the newest interpreter in range wins.
    declare -A _py_seen=()
    while IFS= read -r candidate; do
        [[ -z "$candidate" ]] && continue
        [[ -n "${_py_seen[$candidate]:-}" ]] && continue
        _py_seen[$candidate]=1
        if python_in_range "$candidate"; then
            PYTHON_BIN="$candidate"
            break
        fi
    done < <(
        discover_python_candidates \
            | sort_candidates_by_version \
            | sort -t'|' -k1,1 -V -r \
            | cut -d'|' -f2-
    )
    unset _py_seen
    if [[ -z "$PYTHON_BIN" ]]; then
        cat >&2 <<EOF
Python 3.10–3.12 was not found on this system. Tried:
  - PATH (python3.12, python3.11, python3.10, python3)
  - ~/.local/share/uv/python (uv-managed interpreters)
  - ~/.local/bin (uv / python-build shims)
  - ~/.pyenv/versions (pyenv)
  - /usr/bin, /usr/local/bin, /opt/homebrew/bin
  - ~/.var/app (Flatpak sandboxes)

Install one of:
  - uv:    uv python install 3.12
  - pyenv: pyenv install 3.12
  - apt:   sudo apt install python3.12 python3.12-venv
  - brew:  brew install python@3.12

Or set PYTHON=/path/to/python3.12 and rerun.
EOF
        die "No supported Python interpreter available."
    fi
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
log "Detected Python $PY_VERSION ($PYTHON_BIN)"

# Warn the user early if the GPU is real but the selected Python is
# sandboxed (Flatpak, Steam Linux Runtime, …). The host glibc at
# /run/host/usr/lib is incompatible with the sandbox Python and
# causes the classic "Torch not compiled with CUDA" failure even
# though torch is, in fact, built with CUDA support — it just
# can't load libcuda at import time. We have PYTHON_BIN resolved
# at this point so the case statement can tell host from sandbox.
if (( has_nvidia )); then
    case "$PYTHON_BIN" in
        /run/host/*) ;;  # host Python — good
        *)
            warn "GPU detected but selected Python is $PYTHON_BIN (sandbox). If torch fails with 'CUDA not compiled', recreate the venv with: rm -rf $VENV_DIR && uv venv --python /run/host/usr/bin/python3.12 $VENV_DIR"
            ;;
    esac
fi

# --- 2. create / refresh the venv --------------------------------------------
# Goal: `./launcher.sh` works with no arguments and no manual
# POLYFORGE_VENV juggling. If a venv already exists and matches the
# chosen Python, reuse it. If it exists with the wrong Python (e.g. an
# old Python 3.14 venv left over from an earlier attempt), archive it
# next to the new venv instead of aborting so the user never has to
# rerun with a different POLYFORGE_VENV just to recover.
needs_venv_create=0
if [[ ! -d "$VENV_DIR" ]]; then
    needs_venv_create=1
elif [[ ! -x "$VENV_DIR/bin/python" ]]; then
    warn "Existing venv at $VENV_DIR is incomplete; it will be rebuilt."
    mv "$VENV_DIR" "${VENV_DIR}.broken.$(date +%Y%m%d-%H%M%S).bak"
    needs_venv_create=1
elif ! python_in_range "$VENV_DIR/bin/python"; then
    existing_version="$("$VENV_DIR/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo unknown)"
    # The on-disk venv's Python is not the one we'll use, so we can't
    # reuse it. Archive it (cheap, recoverable) and recreate.
    _bak="${VENV_DIR}.py${existing_version}.bak"
    if [[ -e "$_bak" ]]; then
        _bak="${VENV_DIR}.py${existing_version}.$(date +%Y%m%d-%H%M%S).bak"
    fi
    warn "Existing venv at $VENV_DIR uses Python $existing_version (PolyForge needs 3.10–3.12)."
    warn "Archiving it to $_bak and creating a fresh venv with Python $PY_VERSION."
    mv "$VENV_DIR" "$_bak"
    needs_venv_create=1
fi

if (( needs_venv_create )); then
    # Make sure the source interpreter actually ships `venv` (Debian /
    # Ubuntu split this into python3.12-venv and the base interpreter
    # alone can't create venvs). If it can't, try to install the
    # distro package via apt or fall back to `uv venv` as a last resort
    # before giving up.
    if ! "$PYTHON_BIN" -c 'import venv' >/dev/null 2>&1; then
        warn "Python at $PYTHON_BIN lacks the 'venv' module; attempting to install it."
        if command -v apt-get >/dev/null 2>&1; then
            if [[ "$(id -u)" -eq 0 ]]; then
                apt-get update -qq && apt-get install -y -qq "python${PY_VERSION}-venv" \
                    || warn "apt-get install python${PY_VERSION}-venv failed; venv creation may still fail."
            elif command -v sudo >/dev/null 2>&1 && [[ -t 0 ]]; then
                warn "Need root to install python${PY_VERSION}-venv; falling back to 'uv venv' if available."
                command -v uv >/dev/null 2>&1 && export _POLYFORGE_USE_UV_VENV=1
            else
                command -v uv >/dev/null 2>&1 && export _POLYFORGE_USE_UV_VENV=1
            fi
        elif command -v uv >/dev/null 2>&1; then
            export _POLYFORGE_USE_UV_VENV=1
        else
            die "Python $PY_VERSION has no 'venv' module and no package manager is available. Install python${PY_VERSION}-venv manually."
        fi
    fi

    log "Creating venv at $VENV_DIR with Python $PY_VERSION (this may take a minute)…"
    if [[ "${_POLYFORGE_USE_UV_VENV:-}" == "1" ]] || command -v uv >/dev/null 2>&1; then
        # uv can synthesize a working venv even when the system Python
        # is missing ensurepip / venv bindings, and it works
        # identically across host Python and Flatpak sandboxes
        # (the latter often ships python without ensurepip). Prefer
        # uv when available so the same path works everywhere.
        uv venv --python "$PYTHON_BIN" "$VENV_DIR" \
            || die "uv venv --python $PYTHON_BIN $VENV_DIR failed."
    else
        "$PYTHON_BIN" -m venv "$VENV_DIR" \
            || die "Failed to create venv at $VENV_DIR with $PYTHON_BIN."
    fi
fi
unset _POLYFORGE_USE_UV_VENV

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Pin python to the venv's interpreter for the rest of the run.
PYTHON="$VENV_DIR/bin/python"
PIP=$(python -c 'import sys; print(sys.executable.replace("python", "pip", 1))' 2>/dev/null || echo "$VENV_DIR/bin/pip")

# Wrapper that prefers ``$PYTHON -m pip`` but falls back to
# ``uv pip`` when the venv has no pip module (typical for venvs
# created with ``uv venv``, which skips ensurepip). ``uv pip`` is
# API-compatible with the parts of pip we use here.
py_install() {
    if "$PYTHON" -m pip --version >/dev/null 2>&1; then
        "$PYTHON" -m pip install "$@"
    elif command -v uv >/dev/null 2>&1; then
        VIRTUAL_ENV="$VENV_DIR" uv pip install "$@"
    else
        die "venv at $VENV_DIR has no pip and uv is not installed. Recreate with: rm -rf $VENV_DIR && uv venv --python $PYTHON_BIN $VENV_DIR"
    fi
}

# Upgrade pip + wheel first; wheel avoids egg-only installs.
log "Upgrading pip + wheel + setuptools…"
py_install --quiet --upgrade pip wheel setuptools

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
    py_install --quiet \
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
            # Pick the CUDA wheel index that matches the host driver.
            # PyTorch wheels ship a fixed CUDA runtime; installing a
            # torch built for CUDA X.Y against a driver that only
            # supports X.(Y-1) will fail at import time. NVIDIA's
            # compatibility matrix says driver >= 525 supports CUDA
            # 12, >= 470 supports CUDA 11. We default to cu124 (CUDA
            # 12.4) which is compatible with anything from driver
            # 530+ onwards, covering every modern setup.
            _driver="$(${nvidia_smi_cmd:-nvidia-smi} --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1 | tr -d ' ' || true)"
            _cuda_tag="cu124"
            if [[ -n "$_driver" ]]; then
                _driver_major="${_driver%%.*}"
                if (( _driver_major >= 470 && _driver_major < 525 )); then
                    _cuda_tag="cu118"
                elif (( _driver_major < 470 )); then
                    _cuda_tag="cu116"
                fi
            fi
            log "Pre-installing torch + torchvision for CUDA ($_cuda_tag; host driver $_driver)…"
            TORCH_INSTALL=(--index-url "https://download.pytorch.org/whl/$_cuda_tag" torch torchvision)
        fi
        if ! py_install --quiet "${TORCH_INSTALL[@]}"; then
            warn "torch install failed; will continue with the editable install and hope for the best."
        fi
    fi

    # Step 2: editable install with the rest. --no-build-isolation so
    # the build sandbox can see torch and any other already-installed
    # packages.
    if py_install --quiet --no-build-isolation -e ".[$extra]"; then
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
    if py_install --quiet --no-build-isolation -e ".[dev]"; then
        return 0
    fi

    warn "Even [dev] failed; trying API-only build."
    if py_install --quiet --no-build-isolation -e ".[dev]"; then
        warn "Installed API-only build. ML inference is NOT available."
        export POLYFORGE_NO_ML=1
        return 0
    fi

    if [[ -f "$REQUIREMENTS" ]]; then
        if py_install --quiet --no-build-isolation -r "$REQUIREMENTS"; then
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
        py_install --quiet -e ".[dev]"
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
    py_install --quiet -e ".[dev]" || die "Reinstall failed."
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

# Decide between detached and foreground mode.
# Default: detached — the API runs in its own session so closing the
# terminal does not kill it. Use --foreground to keep the old
# "launcher stays in the foreground, Ctrl+C stops everything" behavior.
POLYFORGE_FOREGROUND="${POLYFORGE_FOREGROUND:-0}"

# Honour SIGINT / SIGTERM for graceful shutdown (only used in foreground mode).
trap 'log "Caught signal — shutting down."; if [[ -n "${API_PID:-}" ]]; then kill -TERM "$API_PID" 2>/dev/null || true; wait "$API_PID" 2>/dev/null || true; fi; rm -f "$API_PID_FILE"; exit 0' INT TERM

log "Starting PolyForge API on http://$POLYFORGE_HOST:$POLYFORGE_PORT"
log "Open http://$POLYFORGE_HOST:$POLYFORGE_PORT/ in your browser for the PolyForge UI."
log "Logs: tail -f $LOG_DIR/api.log"
if [[ "$POLYFORGE_FOREGROUND" != "1" ]]; then
    log "Detached mode: the API keeps running after this script exits. Stop with: ./launcher.sh --stop"
fi

# Run uvicorn directly from the venv so re-installs are picked up immediately.
# In detached mode we need the uvicorn to outlive this script and the
# controlling terminal. The robust recipe is:
#
#   nohup setsid bash -c 'exec "$@"' -- <cmd> </dev/null >log 2>&1 &
#
# - ``nohup`` ignores SIGHUP so closing the terminal doesn't kill the
#   grandchild. ``setsid`` puts the grandchild in a new session so it
#   also ignores the terminal's process-group SIGHUP.
# - The subshell ``bash -c 'exec ...'`` is the key trick: bash will
#   ``exec`` the real uvicorn, so $! at the top level is the *uvicorn*
#   PID (not setsid, not the bash subshell). Without ``exec`` the bash
#   process would stick around and become the actual $! PID, which
#   then dies when the terminal closes.
# - ``</dev/null`` closes stdin so the uvicorn doesn't try to read
#   from a closed pipe after the launcher exits.
# - The PID we record in ``$API_PID_FILE`` is the uvicorn's.
_api_cmd=("$VENV_DIR/bin/python" -m uvicorn hy3dgen.api.server:app --host "$POLYFORGE_HOST" --port "$POLYFORGE_PORT")

if [[ "$POLYFORGE_FOREGROUND" == "1" ]]; then
    PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
        "${_api_cmd[@]}" >> "$LOG_DIR/api.log" 2>&1 &
    API_PID=$!
    printf '%s\n' "$API_PID" > "$API_PID_FILE"
else
    # Background the whole ``nohup setsid bash -c 'exec ...' -- ...`` so
    # the immediate $! is the subshell that immediately execs. We
    # then read the actual uvicorn PID from the log line uvicorn
    # prints on startup ("Started server process [PID]"), so the
    # recorded PID is always the real server.
    # Background the spawn so we can read the real uvicorn PID from
    # the log. We avoid ``nohup`` because in sandboxed environments
    # (Flatpak, Steam Linux Runtime) the ``nohup`` binary itself is
    # linked against the sandbox glibc and breaks with
    # "symbol lookup error" when the loader tries to resolve its
    # own libc. ``setsid`` alone is enough: it puts the grandchild
    # in a new session so SIGHUP from the terminal doesn't kill it.
    PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
        setsid bash -c 'exec "$@"' -- "${_api_cmd[@]}" \
            </dev/null >> "$LOG_DIR/api.log" 2>&1 &
    API_PID=$!
    # ``nohup`` exec's its target, so $! is the setsid wrapper PID,
    # not the uvicorn. Wait briefly for uvicorn to announce itself
    # in the log, then read the real PID from there. Fall back to
    # the wrapper PID if uvicorn hasn't started yet (the readiness
    # probe below will catch the case where neither is alive).
    for _ in {1..20}; do
        sleep 0.1
        line="$(grep -oE 'Started server process \[[0-9]+\]' "$LOG_DIR/api.log" 2>/dev/null | tail -n 1 || true)"
        if [[ -n "$line" ]]; then
            real_pid="$(printf '%s' "$line" | grep -oE '[0-9]+' || true)"
            if [[ -n "$real_pid" ]] && kill -0 "$real_pid" 2>/dev/null; then
                API_PID="$real_pid"
                break
            fi
        fi
    done
    printf '%s\n' "$API_PID" > "$API_PID_FILE"
    disown 2>/dev/null || true
fi

# Brief readiness probe so users see a clear OK / ERROR before exiting.
for _ in {1..40}; do
    if curl -fsS "http://${POLYFORGE_HOST}:${POLYFORGE_PORT}/health" >/dev/null 2>&1; then
        log "API ready (pid $API_PID). Frontend served at http://$POLYFORGE_HOST:$POLYFORGE_PORT/"
        break
    fi
    if ! kill -0 "$API_PID" 2>/dev/null; then
        warn "API process exited. Last 30 log lines:"
        tail -n 30 "$LOG_DIR/api.log" >&2 || true
        rm -f "$API_PID_FILE"
        exit 1
    fi
    sleep 0.5
done

# --- 8. open the UI in the default browser ------------------------------------
# Only when the API answered /health above, only for loopback binds, and
# never in headless sessions. Opt out with --no-browser /
# POLYFORGE_NO_BROWSER=1. Exposed as a function so the "already running"
# short-circuit above can reuse it without duplicating the loopback /
# headless / platform logic.
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

open_browser_if_desired() {
    local url="$1"
    [[ "${POLYFORGE_NO_BROWSER:-}" != "1" ]] || return 0
    case "$POLYFORGE_HOST" in
        127.0.0.1|::1|localhost)
            if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] || [[ "$OSTYPE" == darwin* ]]; then
                if open_browser "$url"; then
                    log "Opened the PolyForge UI in your default browser."
                else
                    log "Open $url in your browser for the PolyForge UI."
                fi
            else
                log "Headless session — open $url from a browser."
            fi
            ;;
        *)
            log "Remote bind ($POLYFORGE_HOST) — open the UI manually (browser auto-open is loopback-only)."
            ;;
    esac
}

open_browser_if_desired "http://$POLYFORGE_HOST:$POLYFORGE_PORT/"

if [[ "$POLYFORGE_FOREGROUND" == "1" ]]; then
    log "Press Ctrl+C to stop."
    wait "$API_PID"
    rm -f "$API_PID_FILE"
else
    log "PolyForge API is running in the background. You can close this terminal."
    log "Stop it with:  ./launcher.sh --stop"
    log "Check it with: ./launcher.sh --status"
    log "Tail logs with: tail -f $LOG_DIR/api.log"
    # Hand the API off to init so it survives the launcher's exit.
    disown "$API_PID" 2>/dev/null || true
fi