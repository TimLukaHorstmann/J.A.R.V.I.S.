#!/bin/bash

# Exit on any error
set -e

# abort if API keys  not set as env vars already
if [ -z "$GOOGLE_MAPS_API_KEY" ]; then
    echo "GOOGLE_MAPS_API_KEY is not set. Please set it in your environment."
    exit 1
fi

if [ -z "$BRAVE_API_KEY" ]; then
  echo "BRAVE_API_KEY is not set. Please set it in your environment."
  exit 1
fi

if [ -z "$ACCUWEATHER_API_KEY" ]; then
    echo "ACCUWEATHER_API_KEY is not set. Please set it in your environment."
    exit 1
fi


mkdir -p logs
PIDS=()

echo "Starting MCP servers..."

# Start Google Maps MCP server
npx -y supergateway --stdio "npx -y @modelcontextprotocol/server-google-maps" \
  --port 4001 \
  --baseUrl http://127.0.0.1:4001 \
  --ssePath /messages \
  --messagePath /message \
  --cors "*" \
  --env GOOGLE_MAPS_API_KEY="$GOOGLE_MAPS_API_KEY" \
  > logs/google-maps.log 2>&1 &
PIDS+=($!)

# Start Brave Search MCP server
npx -y supergateway --stdio "npx -y @modelcontextprotocol/server-brave-search" \
  --port 4002 \
  --baseUrl http://127.0.0.1:4002 \
  --ssePath /messages \
  --messagePath /message \
  --cors "*" \
  --env BRAVE_API_KEY="$BRAVE_API_KEY" \
  > logs/brave-search.log 2>&1 &
PIDS+=($!)

# Start Fetch MCP server
npx -y supergateway --stdio "uvx mcp-server-fetch" \
  --port 4003 \
  --baseUrl http://127.0.0.1:4003 \
  --ssePath /messages \
  --messagePath /message \
  --cors "*" \
  > logs/fetch.log 2>&1 &
PIDS+=($!)

# Weather MCP
npx -y supergateway --stdio "uvx --from git+https://github.com/adhikasp/mcp-weather.git mcp-weather" \
  --port 4004 \
  --baseUrl http://127.0.0.1:4004 \
  --ssePath /messages \
  --messagePath /message \
  --cors "*" \
  --env ACCUWEATHER_API_KEY="$ACCUWEATHER_API_KEY" \
  > logs/weather.log 2>&1 &
PIDS+=($!)

printf "%s\n" "${PIDS[@]}" > .mcp_pids
echo "Started, PIDs: ${PIDS[*]}"
echo "All MCP servers started in background."