# J.A.R.V.I.S. AI Assistant

<p align="center">
  <img src="frontend/assets/images/jarvis_logo2.png" alt="Jarvis Logo" width="100%"/>
</p>

<!-- Badges -->
<p align="center">
  <img src="https://img.shields.io/badge/contributions-welcome-brightgreen" alt="Contributions Welcome"/>
  <!-- <img src="https://img.shields.io/badge/build-passing-brightgreen" alt="Build Status"/> -->
  <img src="https://img.shields.io/badge/license-Non--Commercial-blue" alt="License"/>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python Version"/>
  <img src="https://img.shields.io/badge/docker-ready-blue" alt="Docker"/>
</p>

A voice-enabled advanced AI assistant inspired by the Marvel Cinematic Universe's J.A.R.V.I.S. (Just a Rather Very Intelligent System). This project combines local state-of-the-art large language models (LLMs), speech-to-text (ASR), text-to-speech (TTS), and external tool integration via the Model Context Protocol (MCP) to create a conversational AI experience.

## Features

*   **Voice & Text Interaction:** Communicate via microphone or text input.
*   **Wake Word Detection:** Activate the microphone by saying "Hey Jarvis" (requires browser support).
*   **Streaming Responses:** Receive text and audio responses incrementally.
*   **Multi-Language Support:** Configured for English (`en`) and German (`de`).
*   **Tool Integration (Qwen-Agent & MCP):**
    *   **MCP Servers:** Google Maps, Brave Search, Web Fetch, Weather (AccuWeather).
    *   **Custom Tools:** Includes a sample `magic_function`.
*   **Local LLM:** Powered by `llama-cpp-python` for local inference (configurable model).
*   **ASR:** Uses `Whisper` for accurate speech recognition.
*   **TTS:** Supports multiple engines (`Kokoro`, `Coqui XTTS-v2`, `FastTTS`).
*   **Location Awareness:** Uses browser geolocation to provide context-aware responses (e.g., for weather).
*   **Modern Web UI:** Built with HTML, CSS, and JavaScript.

## Architecture

*   **Frontend ([`frontend/`](frontend/)):**
    *   HTML ([`index.html`](frontend/index.html)), CSS ([`style.css`](frontend/style.css)), and JavaScript ([`script.js`](frontend/script.js)).
    *   Communicates with the backend via WebSockets.
    *   Handles user input (text/audio), displays conversation, plays back audio responses.
*   **Backend ([`backend/`](backend/)):**
    *   **API Server ([`app.py`](backend/app.py)):** Built with FastAPI, handles WebSocket connections, serves the frontend.
    *   **LLM Orchestration:** Uses `Qwen-Agent` to manage conversation flow and tool calls.
    *   **LLM Inference:** Proxies requests to a local `llama-cpp-python` server (or uses its own instance).
    *   **ASR:** Transcribes user audio using the configured Whisper model.
    *   **TTS:** Synthesizes AI responses into audio using the configured TTS engine.
    *   **Tooling:**
        *   Integrates with external tools via MCP servers ([`start_mcp_servers.sh`](backend/start_mcp_servers.sh)).
        *   **Home Assistant:** Fully integrated via MCP.
        *   **Memory:** Long-term memory stored in SQLite, manageable via UI.

## Setup & Installation

1.  **Clone the Repository:**
    ```bash
    git clone <repository-url>
    cd jarvis
    ```

2.  **Backend Setup:**
    *   **Install Dependencies:** This project uses `uv` for package management.
        ```bash
        make setup
        ```
        *(This will automatically create a virtual environment and install dependencies, including `llama-cpp-python` with Metal support on macOS.)*

    *   **Download LLM Model:** The required model (specified in [`backend/config.yaml`](backend/config.yaml)) will be downloaded automatically by `huggingface_hub` on first run if not present in the specified `local_dir`.
    *   **Configure API Keys:** Set the following environment variables for the MCP tools:
        *   `GOOGLE_MAPS_API_KEY`
        *   `BRAVE_API_KEY`
        *   `ACCUWEATHER_API_KEY`
        *   `HASS_URL` & `HASS_TOKEN` (for Home Assistant)
        *(See [`backend/start_mcp_servers.sh`](backend/start_mcp_servers.sh) or [`.vscode/mcp.json`](.vscode/mcp.json) for details)*
    *   **Start MCP Servers:**
        ```bash
        ./start_mcp_servers.sh
        ```
        *(This will run the servers in the background and store their PIDs in `.mcp_pids`)*
    *   **Start Backend Server:**
        ```bash
        make run
        ```
        *(This starts the backend server on http://localhost:8000)*

3.  **Frontend Access:**
    *   Open your web browser and navigate to `http://localhost:8000` (or the host/port you configured).

## Configuration

*   **Backend ([`backend/config.yaml`](backend/config.yaml)):** Configure LLM model details, ASR engine (Whisper settings), TTS engine (Kokoro, Coqui, FastTTS), logging level, and default location.
*   **UI Settings:** Toggle tools (including Home Assistant) and TTS directly from the web interface.
*   **VS Code MCP ([`.vscode/mcp.json`](.vscode/mcp.json)):** Defines MCP server configurations and required API key inputs for easy startup within VS Code using the Model Context Protocol extension.

## Usage

*   **Text Input:** Type your message in the input box and press Enter or click the send button.
*   **Voice Input:**
    *   Click the microphone button to start recording. Speak your query.
    *   Click the button again or wait for silence detection to stop recording.
    *   Alternatively, say "Hey Jarvis" (if wake word detection is active and supported by your browser) to start recording automatically.
*   **Memory Management:** Use the "Memory" button in the sidebar to view, add, or delete long-term memories.
*   **Language Selection:** Use the dropdown menu to select the input/output language (currently English or German).

## Docker

A [`Dockerfile`](backend/Dockerfile) and [`docker-compose.yml`](docker-compose.yml) are provided for containerizing the backend service.

*   **Build:**
    ```bash
    docker-compose build
    ```
*   **Run:**
    ```bash
    # Make sure to pass necessary API keys as environment variables
    # e.g., using a .env file or directly in the command line
    docker-compose up
    ```
*(Note: GPU acceleration within Docker requires specific configurations depending on your host OS and GPU drivers (e.g., NVIDIA Container Toolkit). The provided Dockerfile uses CPU by default unless `llama-cpp-python` is built with GPU flags.)*

## Scripts

*   [`backend/start_mcp_servers.sh`](backend/start_mcp_servers.sh): Starts the necessary MCP tool servers in the background.
*   [`backend/stop_mcp_servers.sh`](backend/stop_mcp_servers.sh): Stops the MCP servers started by the start script.

## Future Plans & Features

We are actively working to improve and extend Jarvis. Planned features and enhancements include:

1. **Online Hosting:**  
   Making Jarvis available to the public via online hosting. We are currently experimenting with deployment on Hugging Face Spaces, but there are still some setup issues to resolve (work in progress).

2. **Extended Language Support:**  
   Expanding language capabilities, especially for German. This depends on the availability and quality of TTS systems for additional languages.

3. **More MCP Servers:**  
   Integrating additional Model Context Protocol (MCP) servers to provide more tools and external integrations.

4. **UI Improvements:**  
   Enhancing the user interface for a more intuitive and engaging experience.

**Contributions are welcome!**  
If you have ideas, suggestions, or would like to contribute code, tools, or documentation, please open an issue or submit a pull request.

## License

Copyright (c) 2025 Tim Luka Horstmann

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to use,
copy, modify, merge, publish, and distribute the Software, subject to the following conditions:

1.  The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

2.  The Software may only be used for **non-commercial purposes**. Commercial use, including but not limited to selling, sublicensing, hosting as a paid service, or using in commercial products, is strictly prohibited **without prior written permission** from the copyright holder.

3.  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
