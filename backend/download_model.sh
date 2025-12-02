#!/bin/bash
set -e

# Function to download a file from Hugging Face
download_model() {
    local repo_id=$1
    local filename=$2
    local local_dir=$3

    echo "Downloading $filename from $repo_id..."
    mkdir -p "$local_dir"
    
    # Use huggingface-cli if available, otherwise curl (but hf-cli is better for caching)
    # We assume huggingface_hub is installed via pip
    uv run huggingface-cli download "$repo_id" "$filename" --local-dir "$local_dir" --local-dir-use-symlinks False
}

# Read config (simple grep, ideally use a yaml parser but this is a quick helper)
# We'll just hardcode the recommended ones for the user to choose or download the active one.

# 1. Llama-3.2-3B-Instruct (Active in config)
REPO_ID="bartowski/mlabonne_Qwen3-4B-abliterated-GGUF"
FILENAME="mlabonne_Qwen3-4B-abliterated-Q4_K_M.gguf"
LOCAL_DIR="pretrained_models/llm"

download_model "$REPO_ID" "$FILENAME" "$LOCAL_DIR"

echo "✅ Model downloaded to backend/$LOCAL_DIR/$FILENAME"
