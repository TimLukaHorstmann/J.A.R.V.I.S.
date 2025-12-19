#!/bin/bash
set -e

# Function to download a file from Hugging Face
download_model() {
    local repo_id=$1
    local filename=$2
    local local_dir=$3

    echo "Downloading $filename from $repo_id..."
    mkdir -p "$local_dir"
    
    uv run hf download "$repo_id" "$filename" --local-dir "$local_dir" --local-dir-use-symlinks False
}

# Read config using python
echo "Reading configuration from config.yaml..."
CONFIG_VALUES=$(uv run python -c "import yaml; config=yaml.safe_load(open('config.yaml')); print(f\"{config['llm']['local']['repo_id']}|{config['llm']['local']['filename']}|{config['llm']['local']['local_dir']}\")")

REPO_ID=$(echo "$CONFIG_VALUES" | cut -d'|' -f1)
FILENAME=$(echo "$CONFIG_VALUES" | cut -d'|' -f2)
LOCAL_DIR=$(echo "$CONFIG_VALUES" | cut -d'|' -f3)

download_model "$REPO_ID" "$FILENAME" "$LOCAL_DIR"

echo "✅ Model downloaded to backend/$LOCAL_DIR/$FILENAME"
