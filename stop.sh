#!/usr/bin/env bash
# Stop WorldSense API server
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDFILE="$SCRIPT_DIR/.worldsense.pid"

if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping WorldSense (PID $PID)..."
        kill "$PID"
        rm -f "$PIDFILE"
        echo "Stopped."
    else
        echo "PID $PID not running. Cleaning up."
        rm -f "$PIDFILE"
    fi
else
    echo "No PID file found. Trying pkill..."
    pkill -f "uvicorn worldsense.api.app" && echo "Stopped." || echo "Not running."
fi
