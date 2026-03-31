#!/usr/bin/env bash
# WorldSense API server startup script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PIDFILE="$SCRIPT_DIR/.worldsense.pid"
LOGFILE="$SCRIPT_DIR/.worldsense.log"

# Kill existing instance if running
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping existing WorldSense server (PID $OLD_PID)..."
        kill "$OLD_PID"
        sleep 1
    fi
    rm -f "$PIDFILE"
fi

# Activate venv
source "$SCRIPT_DIR/.venv/bin/activate"

echo "Starting WorldSense API on port 8766..."
nohup uvicorn worldsense.api.app:app \
    --host 0.0.0.0 \
    --port 8766 \
    --log-level info \
    > "$LOGFILE" 2>&1 &

PID=$!
echo "$PID" > "$PIDFILE"
echo "Started (PID $PID). Logs: $LOGFILE"
