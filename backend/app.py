import os
import logging
import yaml
import asyncio
import json
import re
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from services.audio import AudioService
from services.llm import LLMService
from services.mcp import MCPService
from agent.graph import JarvisAgent

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
agent = None

@app.on_event("startup")
async def startup_event():
    global agent
    await mcp_service.initialize()
    agent = JarvisAgent(llm_service, mcp_service)
    logger.info("✅ JARVIS 2.0 Backend Ready")

@app.on_event("shutdown")
async def shutdown_event():
    await mcp_service.cleanup()

# ─── WebSocket Endpoint ───────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    chat_history = [] # Maintain simple history for this session
    
    try:
        while True:
            message = await websocket.receive()
            
            user_text = ""
            
            if "bytes" in message:
                # Audio received
                audio_bytes = message["bytes"]
                logger.info(f"Received audio: {len(audio_bytes)} bytes")
                user_text = audio_service.transcribe(audio_bytes)
                if not user_text:
                    await websocket.send_json({"type": "error", "message": "Could not understand audio"})
                    continue
                
                # Send back the transcription
                await websocket.send_json({"type": "transcription", "text": user_text})
                
            elif "text" in message:
                # Text received (JSON)
                try:
                    data = json.loads(message["text"])
                    if data.get("type") == "text":
                        # Support both 'text' (frontend) and 'data' (legacy/generic) keys
                        user_text = data.get("text") or data.get("data")
                except Exception as e:
                    logger.error(f"Error parsing text message: {e}")
                    pass
            
            if user_text:
                logger.info(f"User: {user_text}")
                
                # 2. Think & Act (Agent)
                full_response_text = ""
                
                async for event in agent.process_message(user_text, chat_history):
                    if event["type"] == "thought":
                        chunk = event.get("chunk", event.get("content"))
                        # logger.info(f"Thinking chunk: {chunk}") # Too verbose
                        await websocket.send_json({"type": "thought", "chunk": chunk})
                        
                    elif event["type"] == "response":
                        chunk = event.get("chunk", event.get("content"))
                        full_response_text += chunk
                        await websocket.send_json({"type": "text", "chunk": chunk})
                        
                    elif event["type"] == "tool_call":
                        logger.info(f"Calling tool: {event['tool']} with {event['args']}")
                        await websocket.send_json(event)
                        
                    elif event["type"] == "tool_result":
                        logger.info(f"Tool result: {event['tool']} -> {event['content'][:100]}...")
                        await websocket.send_json(event)
                
                logger.info(f"Jarvis: {full_response_text}")
                
                # Update history
                if full_response_text:
                    chat_history.append(user_text)
                    chat_history.append(full_response_text)

                # 3. Speak (TTS)
                # Synthesize and send audio for the full response
                if full_response_text:
                    audio_out = audio_service.synthesize(full_response_text)
                    if audio_out:
                        # Send as binary
                        await websocket.send_bytes(audio_out)

    except WebSocketDisconnect:
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
