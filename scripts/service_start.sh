#!/bin/bash
set -e

# Ensure we are in the project root
cd "$(dirname "$0")/.."

# Go to backend
cd backend

# Trap exit signals to ensure cleanup
cleanup() {
    echo "Stopping MCP servers..."
    ./stop_mcp_servers.sh
}
trap cleanup EXIT

echo "Starting MCP servers..."
./start_mcp_servers.sh

echo "Starting JARVIS Backend..."
# Run uvicorn on localhost:8080 (HTTP)
# Cloudflare Tunnel will handle HTTPS and public access
uv run uvicorn app:app --host 127.0.0.1 --port 8080 --proxy-headers --forwarded-allow-ips '*'
