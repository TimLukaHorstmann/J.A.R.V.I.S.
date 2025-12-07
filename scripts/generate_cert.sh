#!/bin/bash
set -e

# Directory for certificates
CERT_DIR="$(dirname "$0")/../backend/certs"
mkdir -p "$CERT_DIR"

KEY_FILE="$CERT_DIR/key.pem"
CERT_FILE="$CERT_DIR/cert.pem"

if [ -f "$KEY_FILE" ] && [ -f "$CERT_FILE" ]; then
    echo "✅ SSL Certificates already exist."
else
    echo "🔐 Generating self-signed SSL certificates..."
    openssl req -x509 -newkey rsa:4096 -keyout "$KEY_FILE" -out "$CERT_FILE" -days 365 -nodes -subj "/CN=localhost"
    echo "✅ Certificates generated in backend/certs/"
fi
