#!/bin/bash
# Double-click in Finder, or run: bash start-spellbinder.command
set -Eeuo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
RUNTIME="$ROOT/.local-runtime"
API_PID=""
UI_PID=""
TEMP_DIR=""

cleanup() {
  trap - EXIT
  [ -z "$API_PID" ] || kill "$API_PID" 2>/dev/null || true
  [ -z "$UI_PID" ] || kill "$UI_PID" 2>/dev/null || true
  [ -z "$TEMP_DIR" ] || rm -rf "$TEMP_DIR"
}
failed() {
  echo
  echo "Startup failed. Read the error above, then try this launcher again."
  echo "If a dependency needs compiling, install Apple's Command Line Tools"
  echo "with: xcode-select --install"
  if [ -t 0 ]; then read -r -p "Press Return to close..." _; fi
}
trap cleanup EXIT
trap 'failed' ERR
trap 'exit 0' INT TERM HUP

if [ "$(uname -s)" != Darwin ]; then
  echo "This launcher is for macOS. On Windows, use start-spellbinder.bat."
  exit 1
fi
case "$(uname -m)" in
  arm64) NODE_ARCH=arm64 ;;
  x86_64) NODE_ARCH=x64 ;;
  *) echo "Unsupported Mac processor: $(uname -m)"; exit 1 ;;
esac

echo "Spellbinder — Mac setup and startup"
echo "First launch downloads the tools and dependencies; this may take several minutes."
mkdir -p "$RUNTIME/bin" "$RUNTIME/python" "$RUNTIME/cache"
export UV_PYTHON_INSTALL_DIR="$RUNTIME/python"
export UV_CACHE_DIR="$RUNTIME/cache/uv"
export UV_PYTHON_BIN_DIR="$RUNTIME/bin"
export npm_config_cache="$RUNTIME/cache/npm"
export PATH="$RUNTIME/node/bin:$RUNTIME/bin:$PATH"
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/spellbinder.XXXXXX")"

# Astral's standalone installer works without Python, Homebrew, or a compiler.
if [ ! -x "$RUNTIME/bin/uv" ]; then
  echo "Downloading uv (Python installer)..."
  curl --fail --location --retry 3 https://astral.sh/uv/install.sh -o "$TEMP_DIR/install-uv.sh"
  UV_UNMANAGED_INSTALL="$RUNTIME/bin" sh "$TEMP_DIR/install-uv.sh"
fi

# Use an isolated Python rather than Apple's development-tool placeholder.
if [ ! -x "$RUNTIME/venv/bin/python" ]; then
  echo "Installing Python 3.12 and creating the app environment..."
  "$RUNTIME/bin/uv" venv --managed-python --python 3.12 "$RUNTIME/venv"
fi
PYTHON="$RUNTIME/venv/bin/python"

# Official Node binaries include npm. Verify the archive before unpacking.
if [ ! -x "$RUNTIME/node/bin/node" ]; then
  echo "Downloading Node.js 22 and npm..."
  NODE_BASE=https://nodejs.org/dist/latest-v22.x
  curl --fail --location --retry 3 "$NODE_BASE/SHASUMS256.txt" -o "$TEMP_DIR/SHASUMS256.txt"
  NODE_FILE="$(awk -v arch="$NODE_ARCH" '$2 ~ ("-darwin-" arch "\\.tar\\.gz$") {print $2; exit}' "$TEMP_DIR/SHASUMS256.txt")"
  [ -n "$NODE_FILE" ] || { echo "Could not find Node.js for this Mac."; false; }
  curl --fail --location --retry 3 "$NODE_BASE/$NODE_FILE" -o "$TEMP_DIR/$NODE_FILE"
  (cd "$TEMP_DIR"; awk -v file="$NODE_FILE" '$2 == file' SHASUMS256.txt | shasum -a 256 -c -)
  mkdir -p "$TEMP_DIR/node"
  tar -xzf "$TEMP_DIR/$NODE_FILE" -C "$TEMP_DIR/node" --strip-components=1
  mv "$TEMP_DIR/node" "$RUNTIME/node"
fi

# Restart only servers whose command AND working directory match this project.
# This also recognizes servers started by the original Mac launcher.
"$PYTHON" - "$ROOT" <<'PY'
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

root = Path(sys.argv[1]).resolve()

def output(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise SystemExit(f'Could not inspect running servers: {result.stderr.strip()}')
    return result.stdout.strip()

servers = {}
for port, folder in ((8000, 'backend'), (5173, 'frontend')):
    pids = output('/usr/sbin/lsof', '-nP', f'-iTCP:{port}', '-sTCP:LISTEN', '-t')
    for pid_text in set(pids.split()):
        pid = int(pid_text)
        command = output('/bin/ps', '-ww', '-p', str(pid), '-o', 'command=')
        if not command:  # Process finished while being inspected.
            continue
        cwd = output('/usr/sbin/lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn')
        directories = [line[1:] for line in cwd.splitlines() if line.startswith('n')]
        expected = (f'{root}/.local-runtime/venv/bin/python -m uvicorn app.main:app '
                    if port == 8000 else
                    f'{root}/.local-runtime/node/bin/node node_modules/vite/bin/vite.js ')
        if directories != [str(root / folder)] or not command.startswith(expected):
            raise SystemExit(
                f'Port {port} is used by another app (PID {pid}). '
                'Close that app and run this launcher again. It was left running.'
            )
        servers[pid] = command

# Validate every listener before stopping any of them; recheck against PID reuse.
for pid, command in servers.items():
    if output('/bin/ps', '-ww', '-p', str(pid), '-o', 'command=') == command:
        print(f'Stopping existing Spellbinder server (PID {pid})...', flush=True)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

for attempt in range(100):
    busy = []
    for port in (8000, 5173):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                busy.append(port)
    if not busy:
        break
    time.sleep(0.1)
else:
    raise SystemExit(f'Ports {busy} are still busy after waiting 10 seconds. Close the old server window and retry.')

for port in (8000, 5173):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            raise SystemExit(f'Port {port} is already in use. Stop the other Spellbinder launcher or app and try again.')
PY

echo "Checking/installing Python dependencies..."
"$RUNTIME/bin/uv" pip install --python "$PYTHON" --only-binary :all: -r "$ROOT/backend/requirements.txt"

# npm ci uses the committed lock file; skip it on unchanged subsequent runs.
FRONTEND_HASH="$(cat "$ROOT/frontend/package.json" "$ROOT/frontend/package-lock.json" | shasum -a 256 | awk '{print $1}')"
if [ ! -x "$ROOT/frontend/node_modules/.bin/vite" ] || [ "$(cat "$RUNTIME/frontend.hash" 2>/dev/null || true)" != "$FRONTEND_HASH" ]; then
  echo "Installing frontend dependencies..."
  (cd "$ROOT/frontend"; npm ci --no-audit --no-fund)
  echo "$FRONTEND_HASH" > "$RUNTIME/frontend.hash"
fi

echo "Starting API and website..."
(cd "$ROOT/backend"; exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
API_PID=$!
(cd "$ROOT/frontend"; exec "$RUNTIME/node/bin/node" node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort) &
UI_PID=$!

READY=false
for ((attempt=0; attempt<120; attempt++)); do
  kill -0 "$API_PID" 2>/dev/null && kill -0 "$UI_PID" 2>/dev/null || { echo "A server stopped. See its error above."; false; }
  if curl -fsS --max-time 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1 && curl -fsS --max-time 2 http://127.0.0.1:5173/ >/dev/null 2>&1; then
    READY=true
    break
  fi
  sleep 1
done
[ "$READY" = true ] || { echo "Servers did not become ready within the startup window."; false; }
open http://127.0.0.1:5173/ || echo "Open http://127.0.0.1:5173/ in your browser."
echo
echo "Spellbinder is running at http://127.0.0.1:5173/"
echo "Keep this Terminal window open. Press Control+C here to stop both servers."
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$UI_PID" 2>/dev/null; do sleep 2; done
echo "Spellbinder stopped. You can close this Terminal window."
