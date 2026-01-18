#!/bin/bash
# scripts/setup_eufy.sh

# Exit on error
set -e

PROJECT_ROOT="$(dirname "$0")/.."
BACKEND_DIR="$PROJECT_ROOT/backend"
BIN_DIR="$BACKEND_DIR/bin"

mkdir -p "$BIN_DIR"

echo "Setup Eufy Security Integration..."

# 1. Check for Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js (v18+) for eufy-security-ws."
    echo "   curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -"
    echo "   sudo apt-get install -y nodejs"
    exit 1
fi

# 2. Setup eufy-security-ws
if [ ! -d "$BACKEND_DIR/eufy-security-ws" ]; then
    echo "⬇️  Cloning eufy-security-ws..."
    git clone https://github.com/bropat/eufy-security-ws.git "$BACKEND_DIR/eufy-security-ws"
    cd "$BACKEND_DIR/eufy-security-ws"
    echo "📦 Installing npm dependencies..."
    npm install
else
    echo "✅ eufy-security-ws already exists."
fi

# 3. Setup go2rtc
GO2RTC_PATH="$BIN_DIR/go2rtc"
if [ ! -f "$GO2RTC_PATH" ]; then
    echo "⬇️  Downloading go2rtc (linux_arm64)..."
    # Note: Using a specific known good version or latest
    curl -L https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_linux_arm64 -o "$GO2RTC_PATH"
    chmod +x "$GO2RTC_PATH"
    echo "✅ go2rtc installed."
else
    echo "✅ go2rtc already installed."
fi

echo "🎉 Eufy setup complete!"
echo "   Don't forget to add EUFY_USERNAME and EUFY_PASSWORD to your .env file."
