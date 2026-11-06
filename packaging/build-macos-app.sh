#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${NPL_BUILD_DIR:-$ROOT/build/macos}"

[[ "$(uname -s)" == "Darwin" ]] || {
  echo "macOS app builds must run on macOS" >&2
  exit 1
}
python3 -c 'import PyInstaller' >/dev/null 2>&1 || {
  echo "PyInstaller is required; install it in the build environment" >&2
  exit 1
}

rm -rf "$BUILD_DIR"
cd "$ROOT"
python3 -m PyInstaller --clean --noconfirm --name npl \
  --distpath "$BUILD_DIR/dist" --workpath "$BUILD_DIR/work" \
  "$ROOT/packaging/npl.spec"
echo "Built $BUILD_DIR/dist/npl for this Mac architecture"
