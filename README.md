# J.A.R.V.I.S. AI Assistant

<p align="center">
  <img src="frontend/assets/images/jarvis_logo2.png" alt="Jarvis Logo" width="100%"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/contributions-welcome-brightgreen" alt="Contributions Welcome"/>
  <img src="https://img.shields.io/badge/license-Non--Commercial-blue" alt="License"/>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python Version"/>
  <img src="https://img.shields.io/badge/docker-ready-blue" alt="Docker"/>
</p>

Voice-first J.A.R.V.I.S.-inspired assistant powered by LangGraph, FastAPI, Model Context Protocol tools, and a modern web UI. It can run fully locally (llama-cpp + local TTS) or use cloud models such as Gemini and ElevenLabs.

## Highlights
- LangGraph agent with streaming thoughts, tool traces, and WebSocket updates to the UI.
- LLM flexibility: local GGUF models via `llama-cpp-python` or Gemini (`gemini-2.5-flash`) by switching `llm.provider` in `backend/config.yaml`.
- Voice pipeline: Faster-Whisper ASR plus pluggable TTS engines (`elevenlabs`, `kokoro`, `xtts`, `fish_speech`, `chatterbox`).
- Tooling via MCP (Google Maps, Brave Search, Fetch, Weather) plus local tools (search, Wikipedia, news, translator, currency, calculator, Spotify, Home Assistant, OpenWB, system controls, long-term memory).
- UI niceties: wake-word detection, stop generation, TTS toggle, thought toggle, language selector (EN/DE), session history, and editable long-term memory.
- SQLite-backed sessions and memory, served through FastAPI with a lightweight HTML/JS frontend.

## Architecture
- **Frontend (`frontend/`):** Vanilla HTML/CSS/JS served by FastAPI; uses WebSockets for streaming text, audio, tool calls, and thought traces.
- **Backend (`backend/app.py`):** FastAPI server that wires together the audio stack, LangGraph agent (`backend/agent/graph.py`), MCP client, and local tools.
- **Agent:** LangGraph + LangChain messages, streaming `<think>` traces, and tool calls bound to MCP + local tools.
- **Audio:** Faster-Whisper ASR; TTS engines initialized in `backend/services/audio.py`.
- **Data:** SQLite (`backend/database.py`) for chats and long-term memory.

## Quickstart
### Prerequisites
- Python 3.10+, `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node.js 18+ (for `npx supergateway` MCP bridges), `ffmpeg`
- Build tooling for `llama-cpp-python` (cmake, rust/cargo; Metal on macOS is auto-enabled in `make setup`)

### Setup
```bash
git clone <repo-url>
cd JARVIS
make setup          # creates .venv with uv and installs deps
```

Create a `.env` alongside `backend/` for any keys you use:
```
GEMINI_API_KEY=...
ELEVENLABS_API_KEY=...
GOOGLE_MAPS_API_KEY=...
BRAVE_API_KEY=...
HASS_URL=...            # e.g. http://localhost:8123
HASS_TOKEN=...
SPOTIPY_CLIENT_ID=...
SPOTIPY_CLIENT_SECRET=...
SPOTIPY_REDIRECT_URI=...
```

### Choose your LLM
- **Local (fully offline-capable):**
  ```bash
  make download-model   # downloads the GGUF from config.yaml to backend/pretrained_models/llm
  make llm-server       # start llama-cpp-python server on :8000 (separate terminal)
  ```
  Set `llm.provider: local` and ensure `llm.base_url`/`model_alias` match your server.

- **Gemini:**
  Set `llm.provider: gemini` and `GEMINI_API_KEY`. No local model server required.

### Run the app
```bash
make run   # starts MCP servers + FastAPI on http://localhost:8080
```
Open `http://localhost:8080`, then chat via text or mic. Use `make stop` to stop MCP servers.

## Configuration
- `backend/config.yaml` controls:
  - `llm`: provider (`local` or `gemini`), local model repo/filename/alias, context window, base URL.
  - `tts`: engine selection (`elevenlabs`, `kokoro`, `xtts`, `fish_speech`, `chatterbox`) and per-engine settings.
  - `asr`: Faster-Whisper model size, device, and quantization.
  - `tools`: enable/disable local tools (weather, search, calculator, translator, news, Spotify, Home Assistant, OpenWB, system controls, memory).
  - `mcp.servers`: SSE endpoints for Google Maps, Brave Search, Fetch, Weather. Home Assistant MCP is auto-added when `HASS_URL`/`HASS_TOKEN` are set and the tool is enabled.
  - `application`: logging and TTS toggle.
  - `home_assistant`, `openwb`, `spotify`: integration settings.
- UI toggles (wake word, thinking, TTS, tool switches) are exposed in the web app and persist back to `config.yaml`.

## Tools & Integrations
- **MCP servers (via `backend/start_mcp_servers.sh`):** Google Maps, Brave Search, Fetch, Open-Meteo Weather; Home Assistant MCP when credentials are present.
- **Local tools (`backend/tools.py`):** open-meteo weather/time, DuckDuckGo + trafilatura search, Wikipedia, currency conversion, calculator, NewsAPI headlines, translation, Spotify control, Home Assistant (Alexa commands), OpenWB EV charger status, macOS system volume/battery, and long-term memory store/retrieve.
- **Audio:** TTS defaults to ElevenLabs; switch to local engines (Kokoro/XTTS/Fish-Speech/Chatterbox) for fully local runs.

## Docker
`docker-compose.yml` includes services for MCP bridges (Node), an LLM server placeholder, and the FastAPI app (exposed on `8080`). Customize the `llm` service (or point `llm.base_url` at an existing server) before building.
```bash
docker-compose build jarvis
docker-compose up
```

## Useful scripts
- `make setup` — install dependencies with `uv`
- `make download-model` — fetch the configured GGUF from Hugging Face
- `make llm-server` — run a local llama-cpp server using the configured model/context
- `make run` / `make stop` — start/stop MCP servers and the FastAPI app
- `backend/start_mcp_servers.sh` / `backend/stop_mcp_servers.sh` — manual MCP lifecycle helpers

## License

Copyright (c) 2025 Tim Luka Horstmann

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to use,
copy, modify, merge, publish, and distribute the Software, subject to the following conditions:

1.  The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

2.  The Software may only be used for **non-commercial purposes**. Commercial use, including but not limited to selling, sublicensing, hosting as a paid service, or using in commercial products, is strictly prohibited **without prior written permission** from the copyright holder.

3.  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
