#!/usr/bin/env bash
set -e

if [ ! -f .mcp_pids ]; then
  echo "No PID file found. Are the servers running?"
  exit 1
fi

xargs kill < .mcp_pids
rm .mcp_pids
echo "All MCP servers stopped."