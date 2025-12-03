#!/bin/bash

# Navigate to the backend directory
cd "$(dirname "$0")"

# Check if fish-speech directory exists
if [ ! -d "fish-speech" ]; then
    echo "Error: fish-speech directory not found."
    exit 1
fi

echo "Starting Fish Speech API Server..."
cd fish-speech

# Set PYTHONPATH to include current directory to avoid import errors
export PYTHONPATH=$PWD

# Run the server
# Using port 7861 to avoid conflicts with other services
uv run python tools/api_server.py \
    --listen 0.0.0.0:7861 \
    --llama-checkpoint-path "../model_checkpoints/openaudio-s1-mini" \
    --decoder-checkpoint-path "../model_checkpoints/openaudio-s1-mini/codec.pth" \
    --decoder-config-name modded_dac_vq \
    --device cpu

