#!/bin/zsh
set -e

cd "$(dirname "$0")"

echo "Starting JapaneseAgent..."
echo ""

if [ ! -d ".venv" ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv .venv
fi

PYTHON="$PWD/.venv/bin/python"
PIP="$PWD/.venv/bin/pip"

if ! "$PYTHON" -c "import openai" >/dev/null 2>&1; then
  echo "Installing dependencies..."
  "$PIP" install -r requirements.txt
fi

echo ""
"$PYTHON" -m japanese_agent.gui

echo ""
echo "Press Enter to close this window."
read
