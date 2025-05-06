#!/usr/bin/env bash
set -e

if [ ! -f .mcp_pids ]; then
  echo "No PID file found. Are the servers running?"
  exit 1
fi

while read -r PID PORT; do
  if kill "$PID" 2>/dev/null; then
    echo "Killed process $PID on port $PORT"
  else
    echo "Failed to kill PID $PID. Trying to kill process on port $PORT..."
    PID_FROM_PORT=$(lsof -ti tcp:"$PORT")
    if [ -n "$PID_FROM_PORT" ]; then
      kill "$PID_FROM_PORT"
      echo "Killed PID $PID_FROM_PORT on port $PORT"
    else
      echo "No process found on port $PORT"
    fi
  fi
done < .mcp_pids

rm .mcp_pids
echo "All MCP servers stopped."
