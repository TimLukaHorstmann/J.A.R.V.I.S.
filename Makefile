.PHONY: setup run clean

# Detect OS for specific build flags
OS := $(shell uname -s)

setup:
	@echo "Setting up environment with uv..."
	@if ! command -v uv >/dev/null 2>&1; then \
		echo "uv not found. Please install it: curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		exit 1; \
	fi
	cd backend && uv venv
	@echo "Installing dependencies..."
	@if [ "$(OS)" = "Darwin" ]; then \
		echo "Detected macOS. Installing llama-cpp-python with Metal support..."; \
		cd backend && CMAKE_ARGS="-DLLAMA_METAL=ON" FORCE_CMAKE=1 uv pip install --no-binary llama-cpp-python -e .; \
	else \
		cd backend && uv pip install -e .; \
	fi
	@echo "Setup complete."

download-model:
	@echo "Downloading configured LLM..."
	cd backend && ./download_model.sh

llm-server:
	@echo "Starting Local LLM Server..."
	@# Default to Llama-3.2-3B if not specified in config (handled by the python script args usually, but here we hardcode the command for now)
	@# We read the model path from the config or use a default. 
	@# For simplicity in the Makefile, we'll use a fixed path or environment variable.
	cd backend && uv run python -m llama_cpp.server --model pretrained_models/llm/mlabonne_Qwen3-4B-abliterated-Q4_K_M.gguf --n_gpu_layers -1 --n_ctx 8192 --host 0.0.0.0 --port 8000

run:
	@echo "Starting MCP Servers..."
	cd backend && ./start_mcp_servers.sh
	@echo "Starting JARVIS Backend..."
	cd backend && uv run uvicorn app:app --host 0.0.0.0 --port 8080 --reload

stop:
	@echo "Stopping MCP Servers..."
	cd backend && ./stop_mcp_servers.sh

clean:
	@echo "Cleaning up..."
	rm -rf backend/.venv
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
