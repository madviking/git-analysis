#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' is not installed."
  echo "Install it from https://docs.astral.sh/uv/ (e.g. 'brew install uv'), then re-run."
  exit 1
fi

# Ensure the uv-managed virtualenv exists.
if [ ! -f ".venv/bin/activate" ]; then
  uv venv
fi

# Ensure the project environment is up to date.
uv sync

# Activate the uv-managed virtualenv for this shell, if not already active.
if [ -z "${VIRTUAL_ENV:-}" ] || [ "$(cd "${VIRTUAL_ENV}" 2>/dev/null && pwd -P)" != "$(pwd -P)/.venv" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

python -m git_analysis "$@"
