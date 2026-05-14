#!/usr/bin/env bash
# Usage: source scripts/activate.sh
# This script is intended to be sourced so it activates the project's .venv

VENV_DIR="$PWD/.venv"

if [ -z "$VENV_DIR" ]; then
  echo "Cannot determine project .venv location"
  return 1 2>/dev/null || exit 1
fi

if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo ".venv not found in project root. Create it with: python3 -m venv .venv"
  return 1 2>/dev/null || exit 1
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
echo "Activated virtualenv: $VENV_DIR"
