#!/bin/bash
set -e

# Ensure we are in the project root
cd "$(dirname "$0")/.."

echo "Starting JARVIS..."
cd backend
uv run uvicorn app:app --host 0.0.0.0 --port 8000 --reload --proxy-headers --forwarded-allow-ips '*'
