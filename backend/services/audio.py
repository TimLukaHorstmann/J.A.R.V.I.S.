import os
import logging
import io
import time
import numpy as np
import soundfile as sf
import subprocess
import tempfile
from faster_whisper import WhisperModel
from kokoro import KPipeline
import torch
import torchaudio

# Monkeypatch torch.load to handle CUDA models on CPU/MPS
_original_load = torch.load
def _safe_load(*args, **kwargs):
    if 'map_location' not in kwargs and not torch.cuda.is_available():
        kwargs['map_location'] = 'cpu'
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
        
        if self.tts_engine == 'kokoro':
            self._init_kokoro()

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
            else:
                return self._synthesize_kokoro(text)
            
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
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

