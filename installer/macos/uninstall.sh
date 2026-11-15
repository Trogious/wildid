#!/bin/bash
# WildID for macOS: uninstall. Run it from Terminal, as yourself (no sudo):
#
#     bash "$HOME/Library/Application Support/WildID/uninstall.sh"
#
# Removes the program (~/Library/Application Support/WildID), the Lightroom Classic plug-in
# (~/Library/Application Support/Adobe/Lightroom/Modules/wildid.lrplugin) and the PATH line
# install.sh may have added to ~/.zprofile and ~/.bash_profile. The models, the species lists
# and the Hugging Face cache stay, so a reinstall needs no new download.
#
# Options:
#   --purge   also delete the downloads: ~/Library/Caches/wildid (detector, SpeciesNet,
#             species lists) and WildID's three model folders in the Hugging Face cache
#   --yes     do not ask for confirmation
# (end of help)

# Everything runs inside main(), so bash has read the whole file before the folder that holds
# this script is deleted.
main() {
    set -u
    local purge=0 yes=0 answer json pid hub repo

    die() {
        echo "uninstall.sh: $*" >&2
        exit 1
    }

    while [ $# -gt 0 ]; do
        case "$1" in
            --purge) purge=1 ;;
            -y | --yes) yes=1 ;;
            -h | --help)
                sed -n '2,/^# (end of help)/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'
                exit 0
                ;;
            *)
                echo "uninstall.sh: unknown option: $1 (try --help)" >&2
                exit 2
                ;;
        esac
        shift
    done

    [ -n "${HOME:-}" ] && [ -d "$HOME" ] || die "HOME is not set to your home folder."
    [ "$(id -u)" != "0" ] || die "run it as yourself, without sudo."
    local app_dir="$HOME/Library/Application Support/WildID"
    local plugin_dir="$HOME/Library/Application Support/Adobe/Lightroom/Modules/wildid.lrplugin"
    local cache_dir="$HOME/Library/Caches/wildid"
    local marker="# WildID (added by install.sh; uninstall.sh removes this line)"

    if [ "$yes" != 1 ]; then
        [ -t 0 ] || die "not asking in a non-interactive shell: re-run with --yes."
        if [ "$purge" = 1 ]; then
            printf 'Remove WildID, its Lightroom plug-in AND the downloaded models and species lists? [y/N] '
        else
            printf 'Remove WildID and its Lightroom plug-in (downloaded models are kept)? [y/N] '
        fi
        read -r answer
        case "$answer" in
            y | Y | yes | Yes | YES) ;;
            *)
                echo "Nothing was removed."
                exit 0
                ;;
        esac
    fi

    # stop a running server first: it runs from the folder that is about to go
    json="$cache_dir/serve.json"
    if [ -f "$json" ]; then
        pid="$(tr -d '\n' <"$json" | sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')"
        if [ -n "$pid" ] && ps -p "$pid" -o command= 2>/dev/null | grep -q "wildid serve"; then
            kill "$pid" 2>/dev/null && echo "Stopped the running WildID server (pid $pid)."
        fi
    fi

    # the PATH line, wherever install.sh put it (the file itself is kept, with its permissions)
    local profile tmp
    for profile in "$HOME/.zprofile" "$HOME/.bash_profile"; do
        if [ -f "$profile" ] && grep -qF "$marker" "$profile"; then
            tmp="$profile.wildid-tmp"
            grep -vF "$marker" "$profile" >"$tmp"
            cat "$tmp" >"$profile" && rm -f "$tmp"
            echo "PATH: removed the WildID line from $profile."
        fi
    done

    if [ -e "$plugin_dir" ] || [ -L "$plugin_dir" ]; then
        rm -rf "${plugin_dir:?}"
        echo "Removed the Lightroom plug-in: $plugin_dir"
    fi

    if [ "$purge" = 1 ]; then
        if [ -d "$cache_dir" ]; then
            rm -rf "${cache_dir:?}"
            echo "Removed $cache_dir"
        fi
        hub="${HF_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}"
        for repo in models--imageomics--bioclip-2 models--imageomics--bioclip-2.5-vith14 \
            datasets--imageomics--TreeOfLife-200M; do
            if [ -d "$hub/$repo" ]; then
                rm -rf "${hub:?}/$repo"
                echo "Removed $hub/$repo"
            fi
        done
    else
        echo "Kept the downloads: $cache_dir and the models in the Hugging Face cache."
        echo "To delete them as well, run the uninstall.sh of the unzipped download with --purge."
    fi

    # last: the folder this script lives in
    case "$app_dir" in
        */Library/Application\ Support/WildID) ;;
        *) die "refusing to remove an unexpected folder: $app_dir" ;;
    esac
    if [ -d "$app_dir" ]; then
        rm -rf "${app_dir:?}"
        echo "Removed $app_dir"
    fi
    echo "WildID is uninstalled. uv's shared download cache (~/.cache/uv) and its Python"
    echo "(~/.local/share/uv) were left alone: other uv projects may use them."
}

main "$@"
exit $?
