import os
import yaml
import sys

# Add current directory to sys.path to ensure imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.audio import AudioService

# Set up paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
INPUT_FILE = "/Users/luka512/Desktop/GitHubProjects/JARVIS/backend/voice_samples/jarvis_sample.wav"
OUTPUT_DIR = os.path.join(BASE_DIR, "voice_samples", "jarvis")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "sample.lab")

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Load config
print(f"Loading config from {CONFIG_PATH}...")
with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)

# Initialize AudioService
print("Initializing AudioService...")
# We might need to mock some parts if they are not needed, but AudioService seems self-contained enough for transcription
audio_service = AudioService(config)

# Read audio file
print(f"Reading audio from {INPUT_FILE}...")
try:
    with open(INPUT_FILE, "rb") as f:
        audio_data = f.read()
except FileNotFoundError:
    print(f"Error: Input file not found at {INPUT_FILE}")
    sys.exit(1)

# Transcribe
print("Transcribing...")
text = audio_service.transcribe(audio_data)

if text:
    print(f"Transcription successful: {text}")
    # Save to file
    with open(OUTPUT_FILE, "w") as f:
        f.write(text)
    print(f"Saved transcription to {OUTPUT_FILE}")
else:
    print("Transcription failed or returned empty string.")
