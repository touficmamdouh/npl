#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${NPL_BUILD_DIR:-$ROOT/build/appimage}"
APPIMAGETOOL="${APPIMAGETOOL:-appimagetool}"
ARCH="$(uname -m)"

command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }
python3 -c 'import PyInstaller' >/dev/null 2>&1 || {
  echo "PyInstaller is required; install it in the build environment" >&2
  exit 1
}
command -v "$APPIMAGETOOL" >/dev/null 2>&1 || {
  echo "appimagetool is required; set APPIMAGETOOL to its path" >&2
  exit 1
}

cd "$ROOT"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/appdir/usr/bin"
python3 -m PyInstaller --clean --noconfirm --distpath "$BUILD_DIR/dist" \
  --workpath "$BUILD_DIR/work" "$ROOT/packaging/npl.spec"
install -m 0755 "$BUILD_DIR/dist/npl" "$BUILD_DIR/appdir/usr/bin/npl"
install -m 0755 "$ROOT/packaging/AppRun" "$BUILD_DIR/appdir/AppRun"
install -m 0644 "$ROOT/packaging/npl.desktop" "$BUILD_DIR/appdir/npl.desktop"
install -m 0644 "$ROOT/packaging/npl.svg" "$BUILD_DIR/appdir/npl.svg"
"$APPIMAGETOOL" "$BUILD_DIR/appdir" "$ROOT/npl-${ARCH}.AppImage"
echo "Built $ROOT/npl-${ARCH}.AppImage"
