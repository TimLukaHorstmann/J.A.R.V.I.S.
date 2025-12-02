import os
import logging
import io
import time
import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel
from kokoro import KPipeline
import torch

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

        # Initialize TTS (Kokoro)
        tts_config = config['tts']['kokoro']
        logger.info("Loading Kokoro TTS...")
        # Kokoro automatically handles device selection usually, but we can be explicit if needed.
        # It uses onnxruntime or torch. 
        self.tts_pipeline = KPipeline(lang_code=tts_config['lang_code'])
        self.tts_voice = tts_config['voice']
        self.sample_rate = tts_config.get('sample_rate', 24000)

    def transcribe(self, audio_buffer: bytes) -> str:
        """Transcribes raw audio bytes to text."""
        start = time.time()
        try:
            # Convert bytes to float32 numpy array
            # Assuming 16kHz mono input from frontend
            audio_data, _ = sf.read(io.BytesIO(audio_buffer), dtype='float32')
            
            segments, info = self.asr_model.transcribe(audio_data, beam_size=5)
            text = " ".join([segment.text for segment in segments]).strip()
            
            logger.info(f"Transcribed in {time.time() - start:.2f}s: '{text}'")
            return text
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return ""

    def synthesize(self, text: str) -> bytes:
        """Synthesizes text to audio bytes (WAV)."""
        start = time.time()
        try:
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
            logger.info(f"Synthesized in {time.time() - start:.2f}s")
            return out_buf.getvalue()
            
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return b""
