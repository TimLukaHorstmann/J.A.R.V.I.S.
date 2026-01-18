#!/bin/bash
# Start go2rtc streaming server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$SCRIPT_DIR/bin"
CONFIG_FILE="$SCRIPT_DIR/go2rtc.yaml"

# Check if go2rtc exists
if [ ! -f "$BIN_DIR/go2rtc" ]; then
    echo "❌ go2rtc not found. Run: ./scripts/setup_eufy.sh"
    exit 1
fi

# Create default config if it doesn't exist
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" <<EOF
# go2rtc configuration
api:
  listen: ":1984"

streams:
  # Streams will be added dynamically via API
  # Format: stream_name: rtsp://user:pass@ip/path

webrtc:
  listen: ":8555"

log:
  level: info
EOF
    echo "✅ Created default go2rtc config"
fi

echo "✅ Starting go2rtc on port 1984..."
cd "$SCRIPT_DIR"
exec "$BIN_DIR/go2rtc" -c "$CONFIG_FILE"
