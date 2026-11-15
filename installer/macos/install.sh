#!/bin/bash
# WildID for macOS: per-user installer. Run it from Terminal, as yourself (no sudo):
#
#     bash ~/Downloads/WildID-<version>-macos-arm64/install.sh
#
# Start it with "bash" as shown. The download is not signed, and macOS blocks an unsigned
# script that is double-clicked or started as ./install.sh; a script handed to bash is not
# subject to that check. Nothing outside your home folder is touched and no password is asked.
#
# What it does:
#   1. copies WildID to   ~/Library/Application Support/WildID
#   2. clears the download quarantine flag on what it copied, so macOS lets it run
#   3. copies the Lightroom Classic plug-in to
#        ~/Library/Application Support/Adobe/Lightroom/Modules/wildid.lrplugin
#      and writes engine.json there, which tells the plug-in where WildID lives
#   4. downloads its own Python and the libraries it needs (uv sync; needs the network).
#      A Python this Mac already has is never used (python-preference in pyproject.toml).
#   5. offers to put the wildid commands on your PATH (one line in ~/.zprofile)
# Running it again from a newer download upgrades in place. Models and species lists live in
# ~/Library/Caches/wildid and in the Hugging Face cache; this script never touches them.
#
# Options:
#   --path / --no-path   answer the PATH question in advance
#   --no-sync            skip step 4; the launchers download the environment on first use
# (end of help)
set -u

MIN_MACOS=14

die() {
    echo "install.sh: $*" >&2
    exit 1
}

[ -n "${HOME:-}" ] && [ -d "$HOME" ] || die "HOME is not set to your home folder."
APP_DIR="$HOME/Library/Application Support/WildID"
MODULES_DIR="$HOME/Library/Application Support/Adobe/Lightroom/Modules"
PLUGIN_DIR="$MODULES_DIR/wildid.lrplugin"
CACHE_DIR="$HOME/Library/Caches/wildid"
LOG="$APP_DIR/install.log"
MARKER="# WildID (added by install.sh; uninstall.sh removes this line)"
# single quotes on purpose: $HOME and $PATH are expanded by the shell that reads the profile
PATH_LINE='export PATH="$HOME/Library/Application Support/WildID/bin:$PATH"'

ADD_PATH=ask
SYNC=1
while [ $# -gt 0 ]; do
    case "$1" in
        --path) ADD_PATH=yes ;;
        --no-path) ADD_PATH=no ;;
        --no-sync) SYNC=0 ;;
        -h | --help)
            sed -n '2,/^# (end of help)/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "install.sh: unknown option: $1 (try --help)" >&2
            exit 2
            ;;
    esac
    shift
done

say() {
    printf '%s\n' "$*"
    printf '%s\n' "$*" >>"$LOG" 2>/dev/null
}

json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

# A server left over from the previous install would keep running the old code: stop it.
# The plug-in starts the new one when it needs it.
stop_server() {
    local json="$CACHE_DIR/serve.json" pid
    [ -f "$json" ] || return 0
    pid="$(tr -d '\n' <"$json" | sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')"
    [ -n "$pid" ] || return 0
    if ps -p "$pid" -o command= 2>/dev/null | grep -q "wildid serve"; then
        kill "$pid" 2>/dev/null && say "Stopped the running WildID server (pid $pid)."
    fi
    return 0
}

add_path_line() {
    local file="$1"
    if [ -f "$file" ] && grep -qF "$MARKER" "$file"; then
        say "PATH: $file already has the WildID line."
        return 0
    fi
    if printf '\n%s  %s\n' "$PATH_LINE" "$MARKER" >>"$file"; then
        say "PATH: added one line to $file (open a new Terminal window to use it)."
    else
        say "PATH: could not write $file."
    fi
}

# --- checks -----------------------------------------------------------------------------------
[ "$(uname -s)" = "Darwin" ] || die "this installer is for macOS."
[ "$(id -u)" != "0" ] ||
    die "run it as yourself, without sudo: WildID installs into your own home folder."
[ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ] ||
    die "WildID needs a Mac with Apple Silicon (M1 or newer). Intel Macs are not supported."
OS_VERSION="$(sw_vers -productVersion)"
[ "${OS_VERSION%%.*}" -ge "$MIN_MACOS" ] 2>/dev/null ||
    die "WildID needs macOS $MIN_MACOS or newer (this Mac runs macOS $OS_VERSION)."
SRC="$(cd "$(dirname "$0")" && pwd)"
for item in uv VERSION uninstall.sh app/pyproject.toml app/uv.lock app/.python-version app/src \
    bin/wildid bin/wildid-setup bin/wildid-server-start wildid.lrplugin/Info.lua; do
    [ -e "$SRC/$item" ] ||
        die "the installer folder is incomplete: $item is missing. Unzip the whole download and run install.sh from inside it."
done
[ "$SRC" != "$APP_DIR" ] ||
    die "this is the installed copy. Run install.sh from the unzipped download."

mkdir -p "$APP_DIR/app" || die "could not create $APP_DIR"
{
    echo
    echo "=== install.sh $(date '+%Y-%m-%d %H:%M:%S') ==="
} >>"$LOG" 2>/dev/null
say "WildID $(cat "$SRC/VERSION") on macOS $OS_VERSION ($(sysctl -n machdep.cpu.brand_string 2>/dev/null))"
say "Installing into $APP_DIR"

# --- 1. payload -------------------------------------------------------------------------------
stop_server
rm -rf "${APP_DIR:?}/app/src" "${APP_DIR:?}/bin" "${APP_DIR:?}/wildid.lrplugin"
# the uv binary is replaced by rename, never written over in place
cp "$SRC/uv" "$APP_DIR/uv.new" && mv -f "$APP_DIR/uv.new" "$APP_DIR/uv" || die "could not copy uv"
cp "$SRC/app/pyproject.toml" "$SRC/app/uv.lock" "$SRC/app/README.md" "$SRC/app/.python-version" \
    "$APP_DIR/app/" || die "could not copy the project files"
cp -R "$SRC/app/src" "$APP_DIR/app/src" || die "could not copy the sources"
cp -R "$SRC/bin" "$APP_DIR/bin" || die "could not copy the launchers"
cp -R "$SRC/wildid.lrplugin" "$APP_DIR/wildid.lrplugin" || die "could not copy the plug-in"
cp "$SRC/uninstall.sh" "$SRC/VERSION" "$APP_DIR/" || die "could not copy uninstall.sh"
for extra in LICENSE README-macOS.md; do
    [ -f "$SRC/$extra" ] && cp "$SRC/$extra" "$APP_DIR/"
done
chmod +x "$APP_DIR/uv" "$APP_DIR/bin/wildid" "$APP_DIR/bin/wildid-setup" \
    "$APP_DIR/bin/wildid-server-start" "$APP_DIR/uninstall.sh"

# --- 2. quarantine ----------------------------------------------------------------------------
# Files from a downloaded zip carry com.apple.quarantine, and macOS refuses to run an unsigned
# program that has it. Clearing it on our own copy is the standard step for downloaded
# command-line tools.
xattr -dr com.apple.quarantine "$APP_DIR" 2>/dev/null

# --- 3. Lightroom plug-in ---------------------------------------------------------------------
mkdir -p "$MODULES_DIR" || die "could not create $MODULES_DIR"
rm -rf "${PLUGIN_DIR:?}"
cp -R "$APP_DIR/wildid.lrplugin" "$PLUGIN_DIR" || die "could not copy the plug-in to $PLUGIN_DIR"
xattr -dr com.apple.quarantine "$PLUGIN_DIR" 2>/dev/null
cat >"$PLUGIN_DIR/engine.json" <<ENGINE_JSON
{
  "start": "$(json_escape "$APP_DIR/bin/wildid-server-start")",
  "cli": "$(json_escape "$APP_DIR/bin/wildid")",
  "cacheDir": "$(json_escape "$CACHE_DIR")"
}
ENGINE_JSON
[ -s "$PLUGIN_DIR/engine.json" ] || die "could not write $PLUGIN_DIR/engine.json"
say "Lightroom plug-in: $PLUGIN_DIR"

# --- 4. Python environment --------------------------------------------------------------------
SYNC_OK=1
if [ "$SYNC" = 1 ]; then
    say "Downloading the Python environment (about 1.2 GB on disk; needs the network)..."
    if "$APP_DIR/uv" sync --frozen --project "$APP_DIR/app"; then
        say "Python environment ready."
    else
        SYNC_OK=0
        say "The Python environment could not be installed (no network?). Everything else is"
        say "in place: the wildid commands retry the download the first time they are used."
    fi
else
    say "Skipped the Python environment (--no-sync): the wildid commands download it on first use."
fi

# --- 5. PATH ----------------------------------------------------------------------------------
if [ "$ADD_PATH" = ask ]; then
    if [ -t 0 ]; then
        printf 'Put the wildid commands on your PATH (adds one line to ~/.zprofile)? [Y/n] '
        read -r answer
        case "$answer" in
            n | N | no | No | NO) ADD_PATH=no ;;
            *) ADD_PATH=yes ;;
        esac
    else
        ADD_PATH=no
    fi
fi
if [ "$ADD_PATH" = yes ]; then
    add_path_line "$HOME/.zprofile"
    # bash users: the same line, but only where a bash profile already exists
    [ -f "$HOME/.bash_profile" ] && add_path_line "$HOME/.bash_profile"
    SETUP_HINT="in a new Terminal window:  wildid-setup"
else
    say "PATH: left alone. The commands work by full path, as shown below."
    SETUP_HINT="\"$APP_DIR/bin/wildid-setup\""
fi

# --- done -------------------------------------------------------------------------------------
say ""
say "Installed. Next, run the setup wizard (model download and offline check):"
say "    $SETUP_HINT"
say "Then in Lightroom Classic: select photos, Library > Plug-in Extras > Identify species with WildID."
say "Uninstall later with:  bash \"$APP_DIR/uninstall.sh\""
[ "$SYNC_OK" = 1 ] || exit 1
exit 0
