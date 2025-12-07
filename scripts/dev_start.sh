#!/bin/bash
set -e

# Ensure we are in the project root
cd "$(dirname "$0")/.."

echo "Starting JARVIS..."
# Generate certs if needed
./scripts/generate_cert.sh

cd backend
uv run uvicorn app:app --host 0.0.0.0 --port 8000 --reload --proxy-headers --forwarded-allow-ips '*' --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
