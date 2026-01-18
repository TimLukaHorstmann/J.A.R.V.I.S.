#!/bin/bash
# Start eufy-security-ws server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EUFY_DIR="$SCRIPT_DIR/eufy-security-ws"
LOG_DIR="$SCRIPT_DIR/logs"

# Ensure logs directory exists
mkdir -p "$LOG_DIR"

# Load environment variables from .env file
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
    echo "Loading Eufy credentials from $ENV_FILE"
    set -a
    source "$ENV_FILE"
    set +a
fi

# Check if credentials are set
if [ -z "$EUFY_USERNAME" ] || [ -z "$EUFY_PASSWORD" ]; then
    echo "❌ Error: EUFY_USERNAME and EUFY_PASSWORD must be set in .env file"
    echo ""
    echo "Add to .env:"
    echo "  EUFY_USERNAME=your_email@example.com"
    echo "  EUFY_PASSWORD=your_password"
    echo "  EUFY_COUNTRY=DE  # Optional"
    exit 1
fi

# Check if eufy-security-ws is built
if [ ! -d "$EUFY_DIR/dist" ]; then
    echo "Building eufy-security-ws..."
    cd "$EUFY_DIR"
    npm run build
fi

# Create/update config.json with credentials
CONFIG_FILE="$EUFY_DIR/config.json"
cat > "$CONFIG_FILE" <<EOF
{
  "username": "$EUFY_USERNAME",
  "password": "$EUFY_PASSWORD",
  "country": "${EUFY_COUNTRY:-DE}",
  "trustedDeviceName": "JARVIS",
  "eventDurationSeconds": 10,
  "pollingIntervalMinutes": 10,
  "acceptInvitations": false,
  "p2pConnectionSetup": 2,
  "keepAlive": true
}
EOF

# Start the server
echo "✅ Starting Eufy Security WebSocket Server on port 3000..."
echo "   Username: $EUFY_USERNAME"
echo "   Country: ${EUFY_COUNTRY:-DE}"

cd "$EUFY_DIR"
exec node --security-revert=CVE-2023-46809 ./dist/bin/server.js \
    -H 0.0.0.0 \
    -p 3000
