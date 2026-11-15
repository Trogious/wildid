#!/bin/bash
# Build the WildID download for macOS: WildID-<version>-macos-arm64.zip and SHA256SUMS.txt in
# installer/macos/output/. The zip is plain files, so this runs on macOS and on Linux alike
# (CI builds it on ubuntu-latest):
#
#     bash installer/macos/build.sh [--uv-version X.Y.Z]
#
# Steps: download a pinned uv for Apple Silicon and check it against its published .sha256,
# stage payload/WildID-<version>-macos-arm64/ (uv, the locked project, the launchers, the
# Lightroom plug-in, install.sh, uninstall.sh, README-macOS.md, LICENSE, VERSION), zip it.
# Needs: network (for uv), curl, tar, zip, and sha256sum or shasum.
# (end of help)
set -euo pipefail

UV_VERSION="0.11.32" # keep in step with installer/windows/build.ps1 and release.yml

die() {
    echo "build.sh: $*" >&2
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --uv-version)
            UV_VERSION="${2:?--uv-version needs a value}"
            shift
            ;;
        -h | --help)
            sed -n '2,/^# (end of help)/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'
            exit 0
            ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
    shift
done

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
VERSION="$(sed -n 's/^version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$REPO/pyproject.toml" | head -n 1)"
[ -n "$VERSION" ] || die "no version in pyproject.toml"
NAME="WildID-$VERSION-macos-arm64"
PAYLOAD="$HERE/payload"
STAGE="$PAYLOAD/$NAME"
OUT="$HERE/output"
echo "WildID $VERSION, uv $UV_VERSION"

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d ' ' -f 1
    else
        shasum -a 256 "$1" | cut -d ' ' -f 1
    fi
}

rm -rf "${PAYLOAD:?}" "${OUT:?}"
mkdir -p "$STAGE/app" "$STAGE/bin" "$OUT"

# --- uv, pinned and checked against the release's published .sha256 ----------------------------
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP:?}"' EXIT
BASE="https://github.com/astral-sh/uv/releases/download/$UV_VERSION"
ASSET="uv-aarch64-apple-darwin.tar.gz"
curl -fsSL --retry 3 -o "$TMP/$ASSET" "$BASE/$ASSET"
EXPECTED="$(curl -fsSL --retry 3 "$BASE/$ASSET.sha256" | awk '{ print tolower($1); exit }')"
[[ "$EXPECTED" =~ ^[0-9a-f]{64}$ ]] || die "unexpected .sha256 content for uv: '$EXPECTED'"
ACTUAL="$(sha256_of "$TMP/$ASSET")"
[ "$ACTUAL" = "$EXPECTED" ] || die "uv checksum mismatch: $ACTUAL != $EXPECTED"
tar -xzf "$TMP/$ASSET" -C "$TMP"
UV_BIN="$(find "$TMP" -type f -name uv | head -n 1)"
[ -n "$UV_BIN" ] || die "no uv binary in $ASSET"
cp "$UV_BIN" "$STAGE/uv"

# --- the locked project (sources only; the environment is resolved on the target Mac) ----------
cp "$REPO/pyproject.toml" "$REPO/uv.lock" "$REPO/README.md" "$REPO/.python-version" "$STAGE/app/"
cp -R "$REPO/src" "$STAGE/app/src"

# --- the Lightroom plug-in ---------------------------------------------------------------------
cp -R "$REPO/lrplugin/wildid.lrplugin" "$STAGE/wildid.lrplugin"
# engine.json is the machine-specific manifest of a hand-installed dev plug-in (git-ignored);
# install.sh writes the real one on the target Mac
rm -f "$STAGE/wildid.lrplugin/engine.json"

# --- launchers, scripts, documents -------------------------------------------------------------
cp "$HERE/launchers/wildid" "$HERE/launchers/wildid-setup" "$HERE/launchers/wildid-server-start" \
    "$STAGE/bin/"
cp "$HERE/install.sh" "$HERE/uninstall.sh" "$HERE/README-macOS.md" "$REPO/LICENSE" "$STAGE/"
printf '%s\n' "$VERSION" >"$STAGE/VERSION"

find "$STAGE" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$STAGE" -type f \( -name '*.pyc' -o -name '.DS_Store' \) -delete
chmod 755 "$STAGE/uv" "$STAGE/install.sh" "$STAGE/uninstall.sh" "$STAGE/bin/wildid" \
    "$STAGE/bin/wildid-setup" "$STAGE/bin/wildid-server-start"

# A script with Windows line endings does not run on a Mac (a CRLF checkout would cause it;
# .gitattributes pins these files to LF). Fail here rather than on the user's machine.
for script in "$STAGE/install.sh" "$STAGE/uninstall.sh" "$STAGE/bin/wildid" \
    "$STAGE/bin/wildid-setup" "$STAGE/bin/wildid-server-start"; do
    if grep -q "$(printf '\r')" "$script"; then
        die "$script has CRLF line endings"
    fi
    bash -n "$script" || die "$script does not parse"
done

# --- zip + checksum ----------------------------------------------------------------------------
(cd "$PAYLOAD" && zip -r -q -X "$OUT/$NAME.zip" "$NAME")
(cd "$OUT" && printf '%s  %s\n' "$(sha256_of "$NAME.zip")" "$NAME.zip" >SHA256SUMS.txt)
echo "Download: $OUT/$NAME.zip"
cat "$OUT/SHA256SUMS.txt"
