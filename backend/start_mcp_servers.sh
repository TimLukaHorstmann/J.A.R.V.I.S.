#!/bin/bash

# Exit on any error
set -e

# Look for .env file in parent directory and load it if environment variables aren't set
ENV_FILE="../.env"
if [ -f "$ENV_FILE" ]; then
    # Only set variables from .env if they're not already set in the environment
    if [ -z "$GOOGLE_MAPS_API_KEY" ] || [ -z "$BRAVE_API_KEY" ] || [ -z "$ACCUWEATHER_API_KEY" ]; then
        echo "Loading API keys from $ENV_FILE file"
        # Using grep and cut to extract values from the .env file
        [ -z "$GOOGLE_MAPS_API_KEY" ] && export GOOGLE_MAPS_API_KEY=$(grep GOOGLE_MAPS_API_KEY "$ENV_FILE" | cut -d= -f2)
        [ -z "$BRAVE_API_KEY" ] && export BRAVE_API_KEY=$(grep BRAVE_API_KEY "$ENV_FILE" | cut -d= -f2)
        [ -z "$ACCUWEATHER_API_KEY" ] && export ACCUWEATHER_API_KEY=$(grep ACCUWEATHER_API_KEY "$ENV_FILE" | cut -d= -f2)
    fi
fi

# Check if required API keys are set after attempting to load from .env
if [ -z "$GOOGLE_MAPS_API_KEY" ]; then
    echo "GOOGLE_MAPS_API_KEY is not set. Please set it in your environment or in the .env file."
    exit 1
fi

if [ -z "$BRAVE_API_KEY" ]; then
  echo "BRAVE_API_KEY is not set. Please set it in your environment or in the .env file."
  exit 1
fi

if [ -z "$ACCUWEATHER_API_KEY" ]; then
    echo "ACCUWEATHER_API_KEY is not set. Please set it in your environment or in the .env file."
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
npx -y supergateway --stdio "npx -y @kazuph/mcp-fetch" \
  --port 4003 \
  --baseUrl http://127.0.0.1:4003 \
  --ssePath /messages \
  --messagePath /message \
  --cors "*" \
  > logs/fetch.log 2>&1 &
PIDS+=($!)

# Weather MCP
npx -y supergateway --stdio "npx -y @timlukahorstmann/mcp-weather" \
  --port 4004 \
  --baseUrl http://127.0.0.1:4004 \
  --ssePath /messages \
  --messagePath /message \
  --cors "*" \
  --env ACCUWEATHER_API_KEY="$ACCUWEATHER_API_KEY" \
  > logs/weather.log 2>&1 &
PIDS+=($!)

{
  echo "${PIDS[0]} 4001"
  echo "${PIDS[1]} 4002"
  echo "${PIDS[2]} 4003"
  echo "${PIDS[3]} 4004"
} > .mcp_pids
echo "Started, PIDs: ${PIDS[*]}"
echo "All MCP servers started in background."