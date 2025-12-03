import os
import logging
import io
import time
import numpy as np
import soundfile as sf
import subprocess
import tempfile
import requests
import ormsgpack
from faster_whisper import WhisperModel
from kokoro import KPipeline
import torch
import torchaudio

# Try importing TTS (Coqui)
try:
    from TTS.api import TTS
    HAS_XTTS = True
except ImportError:
    HAS_XTTS = False

# Monkeypatch torch.load to handle CUDA models on CPU/MPS
_original_load = torch.load
def _safe_load(*args, **kwargs):
    if 'map_location' not in kwargs and not torch.cuda.is_available():
        kwargs['map_location'] = 'cpu'
    # Fix for PyTorch 2.6+ default weights_only=True breaking older pickles
    if 'weights_only' not in kwargs:
        kwargs['weights_only'] = False
    return _original_load(*args, **kwargs)
torch.load = _safe_load

# Try importing Chatterbox
try:
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    from chatterbox.tts import ChatterboxTTS
    HAS_CHATTERBOX = True
except ImportError:
    HAS_CHATTERBOX = False

logger = logging.getLogger("jarvis.audio")

class AudioService:
    def __init__(self, config):
        self.config = config
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if torch.backends.mps.is_available():
            self.device = "mps" # faster-whisper might not fully support mps yet, usually falls back to cpu or needs specific build. 
            # For now, faster-whisper on Mac often runs best on CPU with int8 quantization or via CoreML if supported.
            # We'll stick to "cpu" for faster-whisper on Mac for stability unless configured otherwise.
            self.asr_device = "cpu" 
        else:
            self.asr_device = self.device

        # Initialize ASR
        asr_config = config['asr']['whisper']
        logger.info(f"Loading Faster-Whisper model ({asr_config['model_size']}) on {self.asr_device}...")
        self.asr_model = WhisperModel(
            asr_config['model_size'], 
            device=self.asr_device, 
            compute_type=asr_config.get('compute_type', 'int8')
        )

        # Initialize TTS
        self.tts_engine = config['tts'].get('engine', 'kokoro')
        
        if self.tts_engine == 'chatterbox':
            if not HAS_CHATTERBOX:
                logger.error("Chatterbox TTS requested but not installed. Falling back to Kokoro.")
                self.tts_engine = 'kokoro'
            else:
                self._init_chatterbox()

        if self.tts_engine == 'xtts':
            if not HAS_XTTS:
                logger.error("XTTS requested but 'TTS' package not installed. Falling back to Kokoro.")
                self.tts_engine = 'kokoro'
            else:
                self._init_xtts()
        
        if self.tts_engine == 'fish_speech':
            self._init_fish_speech()

        if self.tts_engine == 'kokoro':
            self._init_kokoro()

    def _init_fish_speech(self):
        tts_config = self.config['tts']['fish_speech']
        logger.info("Initializing Fish Speech client...")
        self.fs_url = tts_config.get('url', 'http://localhost:7861')
        self.fs_ref_audio = tts_config.get('reference_audio_path')
        self.fs_ref_text = tts_config.get('reference_text_path')
        self.sample_rate = 44100 # Fish Speech usually outputs 44.1kHz

        # Pre-load reference audio/text
        if self.fs_ref_audio and os.path.exists(self.fs_ref_audio):
            with open(self.fs_ref_audio, "rb") as f:
                self.fs_ref_audio_bytes = f.read()
        else:
            logger.warning(f"Fish Speech reference audio not found: {self.fs_ref_audio}")
            self.fs_ref_audio_bytes = None

        if self.fs_ref_text and os.path.exists(self.fs_ref_text):
            with open(self.fs_ref_text, "r") as f:
                self.fs_ref_text_content = f.read().strip()
        else:
            logger.warning(f"Fish Speech reference text not found: {self.fs_ref_text}")
            self.fs_ref_text_content = ""

    def _init_kokoro(self):
        tts_config = self.config['tts']['kokoro']
        logger.info("Loading Kokoro TTS...")
        self.tts_pipeline = KPipeline(lang_code=tts_config['lang_code'])
        self.tts_voice = tts_config['voice']
        self.sample_rate = tts_config.get('sample_rate', 24000)

    def _init_chatterbox(self):
        tts_config = self.config['tts']['chatterbox']
        logger.info("Loading Chatterbox TTS...")
        
        # Determine device for Chatterbox (it supports mps/cuda/cpu)
        # If mps is available, use it if configured, otherwise cpu
        cb_device = tts_config.get('device', 'cpu')
        if cb_device == 'mps' and not torch.backends.mps.is_available():
            cb_device = 'cpu'
            
        self.cb_model_name = tts_config.get('model_name', 'ChatterboxMultilingualTTS')
        
        if self.cb_model_name == 'ChatterboxMultilingualTTS':
            self.cb_model = ChatterboxMultilingualTTS.from_pretrained(device=cb_device)
        else:
            self.cb_model = ChatterboxTTS.from_pretrained(device=cb_device)
            
        self.cb_audio_prompt = tts_config.get('audio_prompt_path')
        self.cb_lang = tts_config.get('language', 'en')
        self.sample_rate = self.cb_model.sr

    def _init_xtts(self):
        tts_config = self.config['tts']['xtts']
        logger.info("Loading XTTS-v2...")
        
        # Check for local model path
        local_model_path = tts_config.get('local_model_path')
        model_args = {}
        
        if local_model_path and os.path.exists(local_model_path):
            logger.info(f"Loading local XTTS model from {local_model_path}")
            model_args['model_path'] = local_model_path
            model_args['config_path'] = os.path.join(local_model_path, "config.json")
            # XTTS v2 usually needs vocab.json too if loading manually, but TTS class might handle it if in same dir
            # If not, we might need to pass it. But let's assume standard folder structure.
        else:
            model_args['model_name'] = tts_config.get('model_name', "tts_models/multilingual/multi-dataset/xtts_v2")
            
        # XTTS on MPS (Mac GPU) has known issues with attention masks in some versions.
        # If we are on MPS, we might need to force CPU for stability if it crashes.
        # The error "Can't infer missing attention mask on mps device" suggests we should use CPU for now.
        if self.device == 'mps':
            logger.warning("XTTS on MPS detected. Forcing CPU for XTTS to avoid attention mask errors.")
            self.xtts_model = TTS(**model_args).to('cpu')
        else:
            self.xtts_model = TTS(**model_args).to(self.device)
        
        self.xtts_speaker_wav = tts_config.get('speaker_wav', 'voice_samples/jarvis_sample.wav')
        self.xtts_language = tts_config.get('language', 'en')
        self.sample_rate = 24000

    def transcribe(self, audio_buffer: bytes) -> str:
        """Transcribes raw audio bytes to text."""
        start = time.time()
        try:
            # Use ffmpeg to convert input bytes to a temporary WAV file
            # This handles various container formats (webm, ogg, mp4) sent by browsers
            with tempfile.NamedTemporaryFile(delete=False) as tmp_in:
                tmp_in.write(audio_buffer)
                tmp_in_name = tmp_in.name
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
                tmp_wav_name = tmp_wav.name

            try:
                # Convert to 16kHz mono wav
                subprocess.run([
                    "ffmpeg", "-y", "-v", "error",
                    "-i", tmp_in_name,
                    "-ar", "16000",
                    "-ac", "1",
                    "-f", "wav",
                    tmp_wav_name
                ], check=True)
                
                # Transcribe directly from the WAV file
                segments, info = self.asr_model.transcribe(tmp_wav_name, beam_size=5)
                text = " ".join([segment.text for segment in segments]).strip()
                
                logger.info(f"Transcribed in {time.time() - start:.2f}s: '{text}'")
                return text
                
            finally:
                # Cleanup temp files
                if os.path.exists(tmp_in_name):
                    os.unlink(tmp_in_name)
                if os.path.exists(tmp_wav_name):
                    os.unlink(tmp_wav_name)
                    
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg conversion failed: {e}")
            return ""
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return ""

    def synthesize(self, text: str) -> bytes:
        """Synthesizes text to audio bytes (WAV)."""
        start = time.time()
        try:
            if self.tts_engine == 'chatterbox':
                return self._synthesize_chatterbox(text)
            elif self.tts_engine == 'xtts':
                return self._synthesize_xtts(text)
            elif self.tts_engine == 'fish_speech':
                return self._synthesize_fish_speech(text)
            else:
                return self._synthesize_kokoro(text)
            
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return b""

    def _synthesize_fish_speech(self, text: str) -> bytes:
        if not self.fs_ref_audio_bytes or not self.fs_ref_text_content:
            logger.error("Fish Speech reference audio/text not loaded.")
            return b""

        # Construct request payload manually to avoid dataclass dependency here
        # Structure:
        # {
        #   "text": "...",
        #   "references": [{"audio": bytes, "text": "..."}],
        #   "format": "wav",
        #   ...
        # }
        
        req_dict = {
            "text": text,
            "references": [{
                "audio": self.fs_ref_audio_bytes,
                "text": self.fs_ref_text_content
            }],
            "reference_id": None,
            "max_new_tokens": 1024,
            "chunk_length": 200,
            "top_p": 0.7,
            "repetition_penalty": 1.2,
            "temperature": 0.7,
            "format": "wav",
            "streaming": False,
            "normalize": True,
        }

        try:
            payload = ormsgpack.packb(req_dict)
            response = requests.post(
                f"{self.fs_url}/v1/tts",
                data=payload,
                headers={"Content-Type": "application/msgpack"},
                timeout=60.0
            )
            
            if response.status_code == 200:
                return response.content
            else:
                logger.error(f"Fish Speech API error: {response.status_code} - {response.text}")
                return b""
        except Exception as e:
            logger.error(f"Fish Speech request failed: {e}")
            return b""

    def _synthesize_kokoro(self, text: str) -> bytes:
        # Kokoro returns a generator or list of audio chunks
        generator = self.tts_pipeline(
            text, 
            voice=self.tts_voice,
            speed=1, 
            split_pattern=r'\n+'
        )
        
        # Concatenate all audio segments
        all_audio = []
        for _, _, audio in generator:
            all_audio.append(audio)
        
        if not all_audio:
            return b""

        full_audio = np.concatenate(all_audio)
        
        # Convert to WAV bytes
        out_buf = io.BytesIO()
        sf.write(out_buf, full_audio, self.sample_rate, format='WAV')
        return out_buf.getvalue()

    def _synthesize_xtts(self, text: str) -> bytes:
        # Check for speaker wav
        speaker_wav = self.xtts_speaker_wav
        if not os.path.exists(speaker_wav):
             logger.warning(f"Speaker sample not found: {speaker_wav}. Using default if available or failing.")
        
        # Generate
        # TTS.tts returns a list of floats
        wav = self.xtts_model.tts(text=text, speaker_wav=speaker_wav, language=self.xtts_language)
        
        # Convert to numpy
        wav_np = np.array(wav, dtype=np.float32)
        
        # Convert to bytes
        out_buf = io.BytesIO()
        sf.write(out_buf, wav_np, self.sample_rate, format='WAV')
        return out_buf.getvalue()

    def _synthesize_chatterbox(self, text: str) -> bytes:
        # Check for audio prompt
        prompt_path = None
        if self.cb_audio_prompt and os.path.exists(self.cb_audio_prompt):
            prompt_path = self.cb_audio_prompt
        elif self.cb_audio_prompt:
            logger.warning(f"Audio prompt file not found: {self.cb_audio_prompt}")

        # Generate
        # Note: Chatterbox generate returns a torch tensor usually? 
        # The example says: wav = model.generate(text); ta.save(..., wav, model.sr)
        # So wav is likely a tensor.
        
        if self.cb_model_name == 'ChatterboxMultilingualTTS':
            # Multilingual
            # It seems it might not support audio_prompt_path in the same way as the base model?
            # The user example showed: multilingual_model.generate(text, language_id="fr")
            # But the user also said "I would also like to provide a audio prompt".
            # Let's try passing it if it exists. If it fails, we catch exception.
            kwargs = {"language_id": self.cb_lang}
            if prompt_path:
                # Assuming it might accept it or we can try. 
                # If the library doesn't support it for multilingual, this might crash.
                # But let's assume the user knows what they are asking for or the library supports it.
                # Actually, looking at common TTS libs, usually multilingual + zero-shot cloning is a thing.
                kwargs["audio_prompt_path"] = prompt_path
            
            wav = self.cb_model.generate(text, **kwargs)
        else:
            # Standard
            kwargs = {}
            if prompt_path:
                kwargs["audio_prompt_path"] = prompt_path
            wav = self.cb_model.generate(text, **kwargs)

        # Convert tensor to bytes
        # wav is likely shape (1, samples) or (samples,)
        if hasattr(wav, 'cpu'):
            wav = wav.cpu()
        
        # Use torchaudio to save to buffer
        out_buf = io.BytesIO()
        torchaudio.save(out_buf, wav, self.sample_rate, format="wav")
        return out_buf.getvalue()

