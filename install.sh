#!/usr/bin/env sh
# Bootstrap claude-toolkit: install the `ctk` command, then run `ctk setup`.
# Asks before every change. Usage: ./install.sh [--yes] [--dry-run]
set -eu

YES=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    -y | --yes) YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h | --help)
      echo "usage: ./install.sh [--yes] [--dry-run]"
      exit 0
      ;;
    *)
      echo "unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

REPO_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)

ask() {
  if [ "$YES" -eq 1 ]; then
    return 0
  fi
  if [ ! -t 0 ]; then
    echo "confirmation required: $1 (no terminal; rerun with --yes after reviewing the plan)" >&2
    exit 3
  fi
  printf '%s [y/N] ' "$1"
  read -r answer
  case "$answer" in
    y | Y | yes | s | sim) return 0 ;;
    *) return 1 ;;
  esac
}

echo "claude-toolkit installer"
echo "plan:"
command -v uv >/dev/null 2>&1 || echo "  0. install uv (https://docs.astral.sh/uv/)"
echo "  1. uv tool install --editable $REPO_DIR   (provides \`ctk\` in ~/.local/bin)"
echo "  2. ctk setup   (shows its own plan and asks before each change)"
[ "$DRY_RUN" -eq 1 ] && exit 0

if ! command -v uv >/dev/null 2>&1; then
  if ask "uv is missing. Install it with the official installer (curl -LsSf https://astral.sh/uv/install.sh | sh)?"; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
    export PATH
  else
    echo "uv is required; install it and rerun ./install.sh" >&2
    exit 1
  fi
fi

if ask "Install the ctk command from $REPO_DIR?"; then
  uv tool install --editable --force "$REPO_DIR"
else
  echo "skipped: ctk was not installed"
  exit 0
fi

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "note: ~/.local/bin is not on PATH; run \`uv tool update-shell\` and restart the shell" ;;
esac

CTK="$HOME/.local/bin/ctk"
command -v ctk >/dev/null 2>&1 && CTK=ctk
if [ "$YES" -eq 1 ]; then
  exec "$CTK" setup --yes
fi
exec "$CTK" setup
