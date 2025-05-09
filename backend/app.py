#!/usr/bin/env python3
import os
# set QWEN_AGENT_MAX_LLM_CALL_PER_RUN to 10 via env var
# os.environ["QWEN_AGENT_MAX_LLM_CALL_PER_RUN"] = "10"

import uuid
import datetime
import io
import json
import logging
import time
import yaml
import ffmpeg
import asyncio
import re

from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
import httpx
import soundfile as sf
import torch
import numpy as np

from transformers import WhisperProcessor, WhisperForConditionalGeneration, GenerationConfig
from torch.serialization import add_safe_globals

from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import XttsAudioConfig, Xtts, XttsArgs
from TTS.config.shared_configs import BaseDatasetConfig
from TTS.api import TTS

from speechbrain.inference.ASR import EncoderDecoderASR

from huggingface_hub import snapshot_download, hf_hub_download

from kokoro import KPipeline

from qwen_agent.agents import Assistant
from langchain_mcp_adapters.client import MultiServerMCPClient

# ─── Your custom tool registration ────────────────────────────────────────────
from qwen_agent.tools.base import BaseTool, register_tool

@register_tool("magic_function")
class MagicFunction(BaseTool):
    """Applies a magic function to an input."""

    description = "Applies a magic function to an input integer and returns the result."
    parameters = [
        {
            "name": "input",
            "type": "integer",
            "description": "The integer to increment",
            "required": True,
        }
    ]

    def call(self, params: str, **kwargs) -> str:
        # `params` is a JSON string; we return JSON too.
        import json, json5
        parsed = json5.loads(params)
        val = parsed["input"]
        return json.dumps({"result": val + 2})

# Load configuration from YAML file
config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
with open(config_path, "r") as f:
    config = yaml.safe_load(f)
# ─── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config["application"]["log_level"]),
    format=config["application"]["log_format"],
)
logger = logging.getLogger("jarvis")
TTS_ENGINE = config["tts"]["engine"]

system_prompt = (
f"""/no_think You are JARVIS, a helpful AI assistant.
Your goal is to assist the user with their requests in a helpful manner.
You should provide accurate and relevant information.

Today is {datetime.datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")}.

Keep your responses concise and to the point, avoiding unnecessary elaboration or disclaimers.
""")

# ─── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI()

server_map = {
  "google_maps": { "url": "http://127.0.0.1:4001/messages", "transport": "sse" },
  "brave_search": { "url": "http://127.0.0.1:4002/messages", "transport": "sse" },
  "fetch": { "url": "http://127.0.0.1:4003/messages", "transport": "sse" },
  "weather": { "url": "http://127.0.0.1:4004/messages", "transport": "sse" },
}   


assistant = None

@app.on_event("startup")
async def startup_event():
    global assistant

    # 1) LLM config for llama-cpp-python
    llm_cfg = {
        "model": "llama-cpp",
        "model_server": "http://localhost:8000/v1",
        "api_key": "EMPTY",
    }

    # 2) Pass both your MCP servers _and_ your custom tool
    function_list = [
        {"mcpServers": server_map},
        "magic_function",
    ]

    assistant = Assistant(llm=llm_cfg, function_list=function_list)
    print("✅ Startup complete: Qwen-Agent ready, proxying to llama-cpp-python server.")

# ─── OpenAI‐compatible HTTP chat endpoint (proxy) ──────────────────────────────
@app.post("/v1/chat/completions")
async def chat_completions(req: dict):
    # Only support the llama-cpp "model" name here
    if req.get("model") != "llama-cpp":
        raise HTTPException(status_code=404, detail="Model not found")

    # Forward the entire payload to the llama-cpp-python server
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/v1/chat/completions",
            json=req,
            headers={"Authorization": "Bearer EMPTY"},
            timeout=None
        )
    return JSONResponse(status_code=resp.status_code, content=resp.json())

# ─── Static file endpoints ────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def get_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "../frontend/index.html"))

@app.get("/{filepath:path}")
async def get_static(filepath: str):
    full_path = os.path.join(os.path.dirname(__file__), "../frontend", filepath)
    return FileResponse(full_path)

# ─── 2) ASR setup (EN & DE) ────────────────────────────────────────────────────
print("Loading ASR models...")
device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
model_id = "openai/whisper-small"
whisper_processor = WhisperProcessor.from_pretrained(model_id)
whisper_model = WhisperForConditionalGeneration.from_pretrained(model_id).to(device)

# Optional fallback SpeechBrain
# asr_en = EncoderDecoderASR.from_hparams(source="speechbrain/asr-crdnn-yesno", savedir="tmp")
# asr_de = EncoderDecoderASR.from_hparams(source="speechbrain/asr-crdnn-commonvoice-de", savedir="tmp")

# ─── 3) TTS setup ─────────────────────────────────────────────────────────────
add_safe_globals([XttsConfig, XttsAudioConfig, BaseDatasetConfig, XttsArgs])
# (Load Coqui / Kokoro / fast tts as in your original snippet…)
if TTS_ENGINE == "coqui":
    print("Downloading XTTS-v2 repo…")
    repo_path = snapshot_download(repo_id=config["tts"]["coqui"]["repo_id"])
    coqui_config = XttsConfig()
    coqui_config.load_json(os.path.join(repo_path, "config.json"))
    model = Xtts.init_from_config(coqui_config)
    model.load_checkpoint(coqui_config, checkpoint_dir=repo_path, use_deepspeed=False)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model.to(device)

    class PatchedGenerationConfig(GenerationConfig):
        def to_dict(self):
            output = super().to_dict()
            output.pop('_pad_token_tensor', None)
            return output

        def __eq__(self, other):
            self_dict = self.to_dict()
            other_dict = self.to_dict()
            return self_dict == other_dict

    # After loading the XTTS model (assuming 'model' is your XTTS model instance)
    # Access the existing generation_config
    gen_cfg = (
        model.gpt.gpt_inference.generation_config
        if hasattr(model.gpt, "gpt_inference")
        else model.gpt.model.generation_config
    )

    # Create a new instance of PatchedGenerationConfig with the existing config's attributes
    patched_gen_cfg = PatchedGenerationConfig(**gen_cfg.to_dict())

    # Handle pad_token_id if it's None
    if patched_gen_cfg.pad_token_id is None:
        if patched_gen_cfg.eos_token_id is not None:
            patched_gen_cfg.pad_token_id = patched_gen_cfg.eos_token_id
            print(f"Set pad_token_id to eos_token_id: {patched_gen_cfg.pad_token_id}")
        else:
            raise ValueError("pad_token_id is None and eos_token_id is also None")

    # Set _pad_token_tensor on the patched config
    pad_t = torch.tensor([patched_gen_cfg.pad_token_id], device=device)
    setattr(patched_gen_cfg, "_pad_token_tensor", pad_t)

    # Ensure streaming-compatible settings
    patched_gen_cfg.return_dict_in_generate = True

    # Replace the model's generation_config with the patched version
    if hasattr(model.gpt, "gpt_inference"):
        model.gpt.gpt_inference.generation_config = patched_gen_cfg
    else:
        model.gpt.model.generation_config = patched_gen_cfg

    print("✅ Streaming support patched successfully")

    # ─── Precompute latents for streaming ─────────────────────────
    sample_clips = {
        "en": os.path.join(repo_path, "samples", "en_sample.wav"),
        "de": os.path.join(repo_path, "samples", "de_sample.wav"),
    }
    xtts_latents = {}
    for lang, path in sample_clips.items():
        clip = path if os.path.exists(path) else "luka.wav"
        xtts_latents[lang] = model.get_conditioning_latents(audio_path=[clip])
    print("XTTS conditioning latents ready.")

elif TTS_ENGINE == "kokoro":
    print("Loading Kokoro TTS model...")
    # Make sure you have installed: kokoro>=0.9.2 and espeak-ng (on Mac: brew install espeak-ng)
    kokoro_pipeline = KPipeline(lang_code=config["tts"]["kokoro"]["lang_code"])
    kokoro_voice = config["tts"]["kokoro"]["voice"]
    # Kokoro sample rate from config
    kokoro_sample_rate = config["tts"]["kokoro"]["sample_rate"]
    print("Kokoro TTS model loaded.")

else:
    # "fast"
    print("Loading fast TTS models...")
    tts_en = TTS(model_name=config["tts"]["fast"]["en_model"], progress_bar=False, gpu=torch.cuda.is_available())
    tts_de = TTS(
        model_name=config["tts"]["fast"]["de_model"]
    )
    print("Fast TTS models loaded.")
# ─── 7) Transcription & synthesis helpers ─────────────────────────────────────
def transcribe(buffer: bytes, language: str = None, format_info: str = None) -> str: # <-- Add language parameter
    """
    Transcribe audio buffer to text using Whisper.

    Tries, in order:
      1) ffmpeg → WAV
      2) soundfile.read as WAV
      3) raw int16 PCM → float32
    """
    # too small to be anything
    if len(buffer) < 3200:
        logger.warning(f"Audio buffer too small: {len(buffer)} bytes")
        return ""

    logger.info(f"Transcribing audio: {len(buffer)} bytes, format hint: {format_info}")
    start_time = time.time()

    wav = None
    sr = None

    # 1) ffmpeg-python fallback (WebM, Opus, whatever → WAV @16 kHz, mono)
    if ffmpeg is not None:
        try:
            out, _ = (
                ffmpeg
                .input("pipe:0")
                .output("pipe:1", format="wav", acodec="pcm_s16le", ac=1, ar="16000")
                .run(input=buffer, capture_stdout=True, capture_stderr=True)
            )
            wav, sr = sf.read(io.BytesIO(out))
            logger.info("Decoded audio via ffmpeg-python fallback")
        except Exception as e:
            logger.warning(f"ffmpeg-python decode failed: {e}")

    # 2) direct WAV read via soundfile
    if wav is None:
        try:
            wav, sr = sf.read(io.BytesIO(buffer))
            logger.info("Decoded audio via soundfile.read")
        except Exception as e:
            logger.warning(f"soundfile.read failed: {e}")

    # 3) raw PCM fallback
    if wav is None:
        try:
            pcm = np.frombuffer(buffer, dtype=np.int16).astype(np.float32) / 32768.0
            wav, sr = pcm, 16000
            logger.info("Interpreted buffer as raw PCM int16 @16 kHz")
        except Exception as e:
            logger.error(f"Raw PCM fallback failed: {e}")

    # give up?
    if wav is None:
        logger.error("All audio decoding methods failed")
        return ""

    # ensure correct sample rate (Whisper expects 16kHz)
    if sr != 16000:
        try:
            import librosa
            wav = librosa.resample(wav, orig_sr=sr, target_sr=16000)
            sr = 16000
            logger.info("Resampled audio to 16 kHz")
        except Exception as e:
            logger.error(f"Resampling failed: {e}")
            return ""

    # make mono
    if wav.ndim > 1:
        wav = wav.mean(axis=1)

    # normalize if too quiet
    if wav.max() < 0.1 and wav.max() > 0:
        logger.warning("Audio signal is very quiet, normalizing")
        wav = wav / wav.max() * 0.95

    # Convert to torch tensor with correct shape
    input_features = whisper_processor(
        wav, 
        sampling_rate=16000, 
        return_tensors="pt"
    ).input_features.to(device)

    whisper_task = "transcribe" # Default task
    # Generate token ids
    with torch.no_grad():
        # Prepare decoder inputs based on the provided language
        forced_decoder_ids = None
        whisper_forced_language = language # Use the language passed to the function
        
        if whisper_forced_language or whisper_task: # Use the function's language variable
            forced_decoder_ids_list = [] # Renamed to avoid confusion
            
            # Add language token if specified
            if whisper_forced_language:
                try:
                    # Ensure language code is valid for Whisper tokenizer
                    lang_token = f"<|{whisper_forced_language}|>"
                    lang_id = whisper_processor.tokenizer.convert_tokens_to_ids(lang_token)
                    if lang_id == whisper_processor.tokenizer.unk_token_id:
                         logger.warning(f"Unknown language code '{whisper_forced_language}' for Whisper. Falling back to auto-detect.")
                         whisper_forced_language = None # Fallback to auto-detect if code is invalid
                    else:
                        forced_decoder_ids_list.append((1, lang_id))
                        logger.info(f"Forcing Whisper language to: {whisper_forced_language}")
                except Exception as e:
                     logger.warning(f"Error setting Whisper language to '{whisper_forced_language}': {e}. Falling back to auto-detect.")
                     whisper_forced_language = None # Fallback on error
            
            # Add task token (always add if language was successfully set or if no language is set but task is)
            if whisper_forced_language or not forced_decoder_ids_list: # Add task if lang was set OR if no lang was set initially
                task_id = whisper_processor.tokenizer.convert_tokens_to_ids(f"<|{whisper_task}|>")
                # Position depends on whether language token was added
                task_position = 2 if whisper_forced_language and forced_decoder_ids_list else 1
                forced_decoder_ids_list.append((task_position, task_id))
            
            # Set the forced decoder inputs if any were added
            forced_decoder_ids = forced_decoder_ids_list if forced_decoder_ids_list else None
        
        # Generate token ids
        predicted_ids = whisper_model.generate(
            input_features,
            forced_decoder_ids=forced_decoder_ids,
            max_length=448,  # Reasonable maximum length
            # Consider adding beam search for potentially better results, but slower:
            # num_beams=5, 
            # early_stopping=True
        )
    
    # Decode the token ids to text
    transcription = whisper_processor.batch_decode(
        predicted_ids, 
        skip_special_tokens=True,
        normalize=True
    )[0]
    
    elapsed = time.time() - start_time
    logger.info(f"Whisper transcription completed in {elapsed:.2f}s: '{transcription}'")

    return transcription




def synthesize(text: str, lang: str = "en") -> bytes:
    # Strip markdown syntax for TTS to avoid reading special characters
    text_for_tts = strip_markdown(text)
    
    # Fallback for fast and other engines
    buf = io.BytesIO()
    if TTS_ENGINE == "coqui":
        sample_clip = os.path.join(repo_path, "samples", f"{lang}_sample.wav")
        sample_clip = sample_clip if os.path.exists(sample_clip) else "luka.wav"
        gpt_latent, speaker_emb = model.get_conditioning_latents(audio_path=[sample_clip])
        out = model.inference(text_for_tts, lang, gpt_latent, speaker_emb)
        sf.write(buf, out["wav"], samplerate=coqui_config.audio["sample_rate"], format="WAV")

    elif TTS_ENGINE == "kokoro":
        # Glue all chunks into one buffer
        parts = []
        for chunk in synthesize_stream_kokoro(text_for_tts):
            parts.append(chunk)
        buf.write(b"".join(parts))
        return buf.getvalue()
    else:
        tts_model = tts_de if lang == "de" else tts_en
        wav = tts_model.tts(text_for_tts)
        sr = tts_model.synthesizer.output_sample_rate
        sf.write(buf, wav, samplerate=sr, format="WAV")
    return buf.getvalue()


def synthesize_stream_xtts(text: str, lang: str = "en"):
    """
    Yields raw WAV‐encoded chunks from XTTS-v2 via inference_stream().
    """
    # Strip markdown syntax for TTS to avoid reading special characters
    text_for_tts = strip_markdown(text)
    
    # grab your precomputed latents
    gpt_latent, speaker_emb = xtts_latents[lang]
    # the inference_stream generator
    for torch_chunk in model.inference_stream(text_for_tts, lang, gpt_latent, speaker_emb):
        # convert to numpy 1d array
        wav = torch_chunk.squeeze().cpu().numpy()
        # pack into a tiny WAV file in memory
        buf = io.BytesIO()
        sf.write(buf, wav, samplerate=coqui_config.audio["sample_rate"], format="WAV")
        yield buf.getvalue()

def synthesize_stream_kokoro(text: str):
    """
    Yields raw WAV‑encoded chunks from Kokoro via streaming pipeline.
    """
    # Strip markdown syntax for TTS to avoid reading special characters
    text_for_tts = strip_markdown(text)
    
    for gs, ps, audio in kokoro_pipeline(text_for_tts, voice=kokoro_voice):
        buf = io.BytesIO()
        # write 24000 Hz WAV
        sf.write(buf, audio, samplerate=kokoro_sample_rate, format="WAV")
        yield buf.getvalue()

def determine_lang(reply: str) -> str:
    # Simple heuristic based on German characters (uncommented)
    return "de" # if any(ch in reply.lower() for ch in ("ä","ö","ü","ß")) else "en"

# Add function to strip markdown syntax for TTS
def strip_markdown(text: str) -> str:
    """
    Remove markdown formatting for TTS to avoid reading special characters.
    """
    # Replace common markdown elements
    result = text
    
    # Headers
    result = re.sub(r'^#+\s+', '', result, flags=re.MULTILINE)
    
    # Bold and italic
    result = re.sub(r'\*\*(.*?)\*\*', r'\1', result)
    result = re.sub(r'\*(.*?)\*', r'\1', result)
    result = re.sub(r'__(.*?)__', r'\1', result)
    result = re.sub(r'_(.*?)_', r'\1', result)
    
    # Lists
    result = re.sub(r'^\s*[-*+]\s+', '', result, flags=re.MULTILINE)
    result = re.sub(r'^\s*\d+\.\s+', '', result, flags=re.MULTILINE)
    
    # Links
    result = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', result)
    
    # Images
    result = re.sub(r'!\[(.*?)\]\(.*?\)', r'\1', result)
    
    # Code blocks and inline code
    result = re.sub(r'```(?:.*?)?\n(.*?)\n```', r'\1', result, flags=re.DOTALL)
    result = re.sub(r'`(.*?)`', r'\1', result)
    
    # Blockquotes
    result = re.sub(r'^\s*>\s+', '', result, flags=re.MULTILINE)
    
    # HTML tags
    result = re.sub(r'<.*?>', '', result)
    
    # Horizontal rules
    result = re.sub(r'^\s*(?:-{3,}|\*{3,}|_{3,})\s*$', '', result, flags=re.MULTILINE)
    
    # Table formatting
    result = re.sub(r'\|', ' ', result)
    result = re.sub(r'^\s*[-:]+\s*$', '', result, flags=re.MULTILINE)
    
    # Escape characters
    result = re.sub(r'\\(.)', r'\1', result)
    
    # Double line breaks to single line breaks and normalize spacing
    result = re.sub(r'\n\s*\n', '\n', result)
    result = re.sub(r'\s+', ' ', result).strip()
    
    return result

# ─── 8) WebSocket endpoint (unchanged) ────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):

    await ws.accept()
    print("WebSocket connection accepted.")

    user_location = None
    user_coordinates = None
    current_request_language = "en"
    meta_received = False
    audio_format = None
    audio_chunks: List[bytes] = []
    seen_tools = {}  # Dictionary to track seen tools and their arguments

    messages = [{"role": "system",  "content": system_prompt}] # this stores the chat history
    # Update the handle_input function for better tool call handling

    async def handle_input(user_content: str, input_language: str):
        await ws.send_json({"event": "processing", "text": "🤖 Jarvis is thinking…"})
        try:
            messages.append({"role": "user", "content": "/no_think" + user_content})
            current_tool = None
            last_assistant_content = ""

            # stream through the assistant
            for responses in assistant.run(messages=messages):
                # 1) LLM wants to call a tool:
                if responses[-1].get("function_call"):
                    fc = responses[-1]["function_call"]
                    tool_name = fc["name"]
                    current_tool = tool_name
                    
                    # Only send a tool_call event if this is a new tool or the arguments have changed significantly
                    current_args = fc["arguments"]
                    if tool_name not in seen_tools or len(current_args) - len(seen_tools[tool_name]) > 20:
                        seen_tools[tool_name] = current_args
                        
                        # wrap it in your <tool_call> tag for history
                        tag = f"<tool_call>{json.dumps(fc)}</tool_call>"
                        # messages.append({"role": "assistant", "content": tag})
                        
                        # Send tool_call event 
                        print(f"Sending tool_call event: {tool_name}")
                        await ws.send_json({
                            "event": "tool_call",
                            "name": tool_name,
                            "arguments": current_args
                        })

                # 2) That tool replied—Qwen-Agent surfaces it as role="function"
                elif responses[-1].get("role") == "function" and current_tool:
                    result = responses[-1].get("content", "")
                    print(f"Sending tool_result event: {current_tool}")
                    # send it as a tool_result event
                    await ws.send_json({
                        "event": "tool_result",
                        "tool": current_tool,
                        "result": result
                    })
                    # Add slight delay to ensure tool result animation plays
                    await asyncio.sleep(0.5)
                    # reset
                    current_tool = None

                # 3) Normal assistant text (e.g. after the function call is done):
                elif responses[-1].get("role") == "assistant" and responses[-1].get("content"):
                    # we'll buffer it until after the loop to synthesize TTS
                    last_assistant_content = responses[-1]["content"]
                    # messages.append(response)

            messages.extend(responses)
            # SYNTHESIZE RESPONSE
            # remove any <think> tags
            reply = last_assistant_content.replace("<think>", "").replace("</think>", "")
            # determine language
            lang = input_language

            print(f"Synthesizing response in '{lang}': {reply}")
            if TTS_ENGINE == "coqui":
                for audio in synthesize_stream_xtts(reply, lang):
                    await ws.send_bytes(audio)
            elif TTS_ENGINE == "kokoro":
                for audio in synthesize_stream_kokoro(reply):
                    await ws.send_bytes(audio)
            else:
                await ws.send_bytes(synthesize(reply, lang))

            await ws.send_json({"event": "text_response", "text": reply})
            print("Sent audio and text response to client.")
            
        except Exception as e:
            print(f"Error in handle_input: {e}")
            await ws.send_json({"event": "error", "text": f"Error: {e}"})
            import traceback
            traceback.print_exc()

    while True:
        msg = await ws.receive()
        if msg.get("type") != "websocket.receive":
            continue

        if "text" in msg:
            try:
                o = json.loads(msg["text"])
                typ = o.get("type")
                if typ == "text":
                    ui = o["text"]
                    tl = o.get("language", "en")
                    if o.get("location"):
                        user_location = o["location"]
                    if o.get("coordinates"):
                        user_coordinates = o["coordinates"]
                    print(f"Received text ({tl}): {ui}")
                    await handle_input(ui, tl)

                elif typ == "audio_meta":
                    current_request_language = o.get("language", "en")
                    audio_format = o.get("format")
                    user_location = o.get("location", user_location)
                    user_coordinates = o.get("coordinates", user_coordinates)
                    meta_received = True
                    audio_chunks = []
                    logger.info(f"Audio meta: lang={current_request_language}, fmt={audio_format}")

            except json.JSONDecodeError:
                logger.error(f"Bad JSON: {msg['text']}")
            continue

        if "bytes" in msg:
            chunk = msg["bytes"]
            if len(chunk) == 0 and meta_received and audio_chunks:
                buf = b"".join(audio_chunks)
                audio_chunks = []
                meta_received = False

                text = transcribe(buf, language=current_request_language, format_info=audio_format)
                await ws.send_json({
                    "event": "transcription",
                    "text": text or "Sorry, couldn't understand."
                })
                await handle_input(text, current_request_language)

            elif len(chunk) > 0:
                audio_chunks.append(chunk)
            continue

    await ws.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
