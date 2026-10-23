#!/bin/bash
# Double-click to create your local administrator and choose a password privately.
set -eu
cd "$(dirname "$0")"
ROOT="$PWD"
PYTHON="$ROOT/.local-runtime/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Run start-spellbinder.command first to install Python."
  read -r -p "Press Return to close..." _
  exit 1
fi
cd "$ROOT/backend"
echo "Creating local administrator: ${1:-bbrown812}"
echo "Enter your chosen password twice. Typing is hidden."
if "$PYTHON" -m app.auth_cli create-user "${1:-bbrown812}" --admin; then
  echo "Account created. Refresh the website to sign in."
else
  echo "Account was not created. See the error above."
fi
read -r -p "Press Return to close..." _
