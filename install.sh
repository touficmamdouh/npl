#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${NPL_REPO_URL:-https://github.com/touficmamdouh/npl.git}"
INSTALL_DIR="${NPL_INSTALL_DIR:-$HOME/.local/share/npl}"
SKIP_APT="${NPL_SKIP_APT:-0}"
SKIP_SYMLINK="${NPL_SKIP_SYMLINK:-0}"
OS_NAME="$(uname -s)"

if [[ $EUID -eq 0 ]]; then
  echo "Run this installer as your normal user; it will ask for sudo when needed." >&2
  exit 1
fi

if [[ "$OS_NAME" == "Linux" && "$SKIP_APT" != "1" ]]; then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "sudo is required to install system packages." >&2
    exit 1
  fi
  missing=()
  command -v curl >/dev/null 2>&1 || missing+=(curl)
  command -v git >/dev/null 2>&1 || missing+=(git)
  command -v vnstat >/dev/null 2>&1 || missing+=(vnstat)
  command -v nethogs >/dev/null 2>&1 || missing+=(nethogs)
  command -v ip >/dev/null 2>&1 || missing+=(iproute2)
  command -v nmcli >/dev/null 2>&1 || missing+=(network-manager)
  command -v iw >/dev/null 2>&1 || missing+=(iw)
  command -v ping >/dev/null 2>&1 || missing+=(iputils-ping)

  if ! command -v python3 >/dev/null 2>&1 || ! python3 -c \
    'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    >/dev/null 2>&1; then
    missing+=(python3 python3-venv)
  elif ! python3 -m venv --help >/dev/null 2>&1; then
    missing+=(python3-venv)
  fi

  if ((${#missing[@]})); then
    if ! command -v apt-get >/dev/null 2>&1; then
      echo "Install these packages manually: ${missing[*]}" >&2
      exit 1
    fi
    sudo apt-get update
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}"
  fi

  sudo systemctl enable --now vnstat >/dev/null 2>&1 || true
elif [[ "$OS_NAME" != "Darwin" && "$OS_NAME" != "Linux" ]]; then
  echo "Unsupported operating system: $OS_NAME" >&2
  exit 1
fi

if [[ -d "$INSTALL_DIR/.git" ]]; then
  git -C "$INSTALL_DIR" pull --ff-only
elif [[ -e "$INSTALL_DIR" ]]; then
  echo "Install directory exists but is not a git checkout: $INSTALL_DIR" >&2
  exit 1
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install \
  --disable-pip-version-check --quiet -r "$INSTALL_DIR/requirements.txt"
chmod +x "$INSTALL_DIR/bin/npl"

if [[ "$SKIP_SYMLINK" != "1" ]]; then
  if [[ "$OS_NAME" == "Linux" ]]; then
    if ! command -v sudo >/dev/null 2>&1; then
      echo "sudo is required to install /usr/local/bin/npl; use NPL_SKIP_SYMLINK=1" >&2
      exit 1
    fi
    sudo ln -sfn "$INSTALL_DIR/bin/npl" /usr/local/bin/npl
  else
    mkdir -p "$HOME/.local/bin"
    ln -sfn "$INSTALL_DIR/bin/npl" "$HOME/.local/bin/npl"
    echo "Add $HOME/.local/bin to PATH if needed."
  fi
fi

"$INSTALL_DIR/bin/npl" --version
printf '\nInstalled. Run: npl\n'
