import os
import logging
import yaml
import asyncio
import json
import re
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from services.audio import AudioService
from services.llm import LLMService
from services.mcp import MCPService
from services.openwb import OpenWBService
from agent.graph import JarvisAgent
from database import DatabaseService
from tools import get_local_tools

# Load environment variables
env_path = os.path.join(os.path.dirname(__file__), "../.env")
if load_dotenv(env_path):
    print(f"✅ Loaded environment variables from {env_path}")
else:
    print(f"⚠️  Warning: .env file not found at {env_path}")

# Load configuration
config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
with open(config_path, "r") as f:
    config = yaml.safe_load(f)

# Logging setup
logging.basicConfig(
    level=getattr(logging, config["application"]["log_level"]),
    format=config["application"]["log_format"],
)
logger = logging.getLogger("jarvis")

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Services
audio_service = AudioService(config)
llm_service = LLMService(config)
mcp_service = MCPService(config)
openwb_service = OpenWBService(config)
db_service = DatabaseService()
agent = None

@app.on_event("startup")
async def startup_event():
    global agent
    await mcp_service.initialize()
    local_tools = get_local_tools(config, openwb_service)
    agent = JarvisAgent(llm_service, mcp_service, local_tools)
    logger.info("✅ JARVIS 2.0 Backend Ready")

@app.on_event("shutdown")
async def shutdown_event():
    await mcp_service.cleanup()

# ─── Settings API ─────────────────────────────────────────────────────────────
def save_config():
    with open(config_path, "w") as f:
        yaml.dump(config, f)

@app.get("/api/settings")
async def get_settings():
    return config

@app.post("/api/settings")
async def update_settings(new_settings: dict):
    global config, agent
    
    # Update specific sections
    if "spotify" in new_settings:
        config["spotify"] = new_settings["spotify"]
        
    if "tools" in new_settings:
        config["tools"] = new_settings["tools"]

    if "application" in new_settings:
        # Merge application settings
        config["application"].update(new_settings["application"])
    
    # Save to file
    save_config()
    
    # Re-initialize local tools to pick up changes (e.g. Spotify enabled/disabled)
    local_tools = get_local_tools(config)
    agent = JarvisAgent(llm_service, mcp_service, local_tools)
    
    return {"status": "updated", "config": config}

# ─── REST API for Sessions ────────────────────────────────────────────────────
@app.get("/api/sessions")
async def get_sessions():
    return db_service.get_sessions()

@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    return db_service.get_session_messages(session_id)

@app.post("/api/sessions")
async def create_session(request: dict):
    title = request.get("title", "New Conversation")
    return {"id": db_service.create_session(title)}

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    db_service.delete_session(session_id)
    return {"status": "ok"}

@app.delete("/api/sessions")
async def delete_all_sessions():
    db_service.delete_all_sessions()
    return {"status": "ok"}

# ─── Memory API ───────────────────────────────────────────────────────────────
@app.get("/api/memory")
async def get_memory():
    return db_service.get_all_memories()

@app.post("/api/memory")
async def add_memory(request: dict):
    key = request.get("key")
    value = request.get("value")
    if not key or not value:
        return JSONResponse(status_code=400, content={"error": "Key and value required"})
    db_service.add_memory(key, value)
    return {"status": "ok"}

@app.delete("/api/memory/{key}")
async def delete_memory(key: str):
    db_service.delete_memory(key)
    return {"status": "ok"}

# ─── WebSocket Endpoint ───────────────────────────────────────────────────────
async def process_conversation(websocket: WebSocket, user_text: str, session_id: str, thinking_enabled: bool = True):
    try:
        # Load history
        messages = db_service.get_session_messages(session_id)
        # Convert to format expected by agent (list of strings or dicts)
        # The agent currently expects a list of strings (alternating user/ai) or similar.
        # Let's assume we just pass the text history for now.
        chat_history = [m["content"] for m in messages if m["type"] == "text"] # Simplified

        # Save user message
        db_service.add_message(session_id, "user", user_text)

        # Prepare prompt (handle thinking toggle)
        prompt_text = user_text
        if not thinking_enabled:
            prompt_text = f"/nothink {user_text}"

        full_response_text = ""
        tts_text = ""
        
        async for event in agent.process_message(prompt_text, chat_history):
            if event["type"] == "thought":
                chunk = event.get("chunk", event.get("content"))
                if chunk and chunk.strip():
                    await websocket.send_json({"type": "thought", "chunk": chunk})
                
            elif event["type"] == "response":
                chunk = event.get("chunk", event.get("content"))
                full_response_text += chunk
                tts_text += chunk
                await websocket.send_json({"type": "text", "chunk": chunk})
                
            elif event["type"] == "tool_call":
                logger.info(f"Calling tool: {event['tool']} with {event['args']}")
                # Reset tts_text so we only TTS the final answer after all tools are done
                tts_text = ""
                await websocket.send_json(event)
                
            elif event["type"] == "tool_result":
                logger.info(f"Tool result: {event['tool']} -> {event['content'][:100]}...")
                await websocket.send_json(event)
        
        logger.info(f"Jarvis: {full_response_text}")
        
        # Save AI response
        if full_response_text:
            db_service.add_message(session_id, "assistant", full_response_text)

        # 3. Speak (TTS)
        tts_enabled = config.get("application", {}).get("tts_enabled", True)
        if tts_text and tts_enabled:
            audio_out = audio_service.synthesize(tts_text)
            if audio_out:
                await websocket.send_bytes(audio_out)
                
        # Signal completion
        await websocket.send_json({"type": "complete"})

    except asyncio.CancelledError:
        logger.info("🛑 Task cancelled")
        await websocket.send_json({"type": "system", "content": "Generation stopped."})
        # Save partial response if needed?
    except Exception as e:
        logger.error(f"Error in processing: {e}")
        await websocket.send_json({"type": "error", "message": str(e)})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Default session
    session_id = db_service.create_session("New Session")
    await websocket.send_json({"type": "session_init", "session_id": session_id})
    
    processing_task = None
    current_thinking_mode = True
    
    try:
        while True:
            message = await websocket.receive()
            
            user_text = ""
            is_stop = False
            
            if "bytes" in message:
                # Audio received
                audio_bytes = message["bytes"]
                user_text = audio_service.transcribe(audio_bytes)
                if not user_text:
                    await websocket.send_json({"type": "error", "message": "Could not understand audio"})
                    continue
                
                await websocket.send_json({"type": "transcription", "text": user_text})
                
            elif "text" in message:
                try:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")
                    
                    if msg_type == "config":
                        current_thinking_mode = data.get("thinking", True)
                        continue
                    elif msg_type == "stop":
                        is_stop = True
                    elif msg_type == "load_session":
                        session_id = data.get("session_id")
                        # Send history to frontend
                        history = db_service.get_session_messages(session_id)
                        await websocket.send_json({"type": "history", "messages": history})
                        continue
                    elif msg_type == "new_session":
                        session_id = db_service.create_session("New Session")
                        await websocket.send_json({"type": "session_init", "session_id": session_id})
                        continue
                    elif msg_type == "text":
                        user_text = data.get("text") or data.get("data")
                        current_thinking_mode = data.get("thinking", True)
                except Exception as e:
                    logger.error(f"Error parsing text message: {e}")
            
            # Handle Stop
            if is_stop:
                if processing_task and not processing_task.done():
                    processing_task.cancel()
                continue

            # Handle New Input
            if user_text:
                if processing_task and not processing_task.done():
                    await websocket.send_json({"type": "error", "message": "Already processing. Please stop first."})
                    continue
                
                # Update title if it's the first message
                messages = db_service.get_session_messages(session_id)
                if len(messages) <= 1: # Just created
                    # Simple heuristic for title: first 30 chars
                    db_service.update_session_title(session_id, user_text[:30] + "...")
                    # Notify frontend to refresh list
                    await websocket.send_json({"type": "session_updated"})

                processing_task = asyncio.create_task(process_conversation(websocket, user_text, session_id, current_thinking_mode))

    except WebSocketDisconnect:
        if processing_task: processing_task.cancel()
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except:
            pass

# ─── Static Files ─────────────────────────────────────────────────────────────
# Mount the frontend directory as a static directory
# This allows serving files like script.js, style.css directly
from fastapi.staticfiles import StaticFiles

# Define the frontend path
FRONTEND_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend"))

# Serve index.html at the root
@app.get("/")
async def get_index():
    index_path = os.path.join(FRONTEND_PATH, "index.html")
    if not os.path.exists(index_path):
        return JSONResponse(status_code=404, content={"error": "Frontend not found"})
    return FileResponse(index_path)

# Mount the frontend directory to serve other static files (js, css, assets)
# We mount it at the root "/" but after the specific "/" route, 
# so it acts as a catch-all for static files.
# However, mounting at "/" in FastAPI can be tricky as it matches everything.
# A better approach for a SPA/simple site:
app.mount("/", StaticFiles(directory=FRONTEND_PATH, html=True), name="frontend")
