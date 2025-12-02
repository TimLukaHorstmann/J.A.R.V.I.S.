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
from database import DatabaseService

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
db_service = DatabaseService()
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

# ─── WebSocket Endpoint ───────────────────────────────────────────────────────
async def process_conversation(websocket: WebSocket, user_text: str, session_id: str):
    try:
        # Load history
        messages = db_service.get_session_messages(session_id)
        # Convert to format expected by agent (list of strings or dicts)
        # The agent currently expects a list of strings (alternating user/ai) or similar.
        # Let's assume we just pass the text history for now.
        chat_history = [m["content"] for m in messages if m["type"] == "text"] # Simplified

        # Save user message
        db_service.add_message(session_id, "user", user_text)

        full_response_text = ""
        
        async for event in agent.process_message(user_text, chat_history):
            if event["type"] == "thought":
                chunk = event.get("chunk", event.get("content"))
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
        
        # Save AI response
        if full_response_text:
            db_service.add_message(session_id, "assistant", full_response_text)

        # 3. Speak (TTS)
        if full_response_text:
            audio_out = audio_service.synthesize(full_response_text)
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
                    
                    if msg_type == "stop":
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

                processing_task = asyncio.create_task(process_conversation(websocket, user_text, session_id))

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
