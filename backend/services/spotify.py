import spotipy
from spotipy.oauth2 import SpotifyOAuth
import logging
import os

logger = logging.getLogger("jarvis.spotify")

class SpotifyService:
    def __init__(self, config):
        self.config = config.get("spotify", {})
        # self.enabled is now controlled by tools.py / config['tools']['spotify']
        # But we still need to initialize if we are instantiated.
        # We'll assume if this service is created, we should try to initialize.
        self.enabled = False 
        self.client = None
        
        self.initialize()

    def initialize(self):
        try:
            # Try to get credentials from config or env vars (support both SPOTIPY_ and SPOTIFY_ prefixes)
            client_id = self.config.get("client_id") or os.getenv("SPOTIPY_CLIENT_ID") or os.getenv("SPOTIFY_CLIENT_ID")
            client_secret = self.config.get("client_secret") or os.getenv("SPOTIPY_CLIENT_SECRET") or os.getenv("SPOTIFY_CLIENT_SECRET")
            redirect_uri = self.config.get("redirect_uri") or os.getenv("SPOTIPY_REDIRECT_URI") or "http://127.0.0.1:8888/callback"
            
            if not client_id or not client_secret:
                logger.warning(f"Spotify credentials not found. Env vars: ID={'Found' if os.getenv('SPOTIPY_CLIENT_ID') else 'Missing'}, Secret={'Found' if os.getenv('SPOTIPY_CLIENT_SECRET') else 'Missing'}")
                self.enabled = False
                return

            self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope="user-read-playback-state,user-modify-playback-state,user-read-currently-playing",
                open_browser=False
            ))
            self.enabled = True
            logger.info("Spotify service initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize Spotify service: {e}")
            self.enabled = False

    def get_active_device(self):
        try:
            devices = self.sp.devices()
            if not devices or not devices.get('devices'):
                return None
            
            # Check for active device
            for device in devices['devices']:
                if device['is_active']:
                    return device['id']
            
            # If no active device, return the first available one
            # Prefer Computer/Smartphone over others if possible, but taking first is usually fine
            return devices['devices'][0]['id']
        except Exception as e:
            logger.error(f"Error getting devices: {e}")
            return None

    def play_music(self, query=None):
        if not self.enabled:
            return "Spotify is not enabled."
        try:
            device_id = self.get_active_device()
            if not device_id:
                return "No active Spotify device found. Please open Spotify on your device."

            if query:
                results = self.sp.search(q=query, limit=1, type='track')
                if results['tracks']['items']:
                    uri = results['tracks']['items'][0]['uri']
                    self.sp.start_playback(device_id=device_id, uris=[uri])
                    return f"Playing {query} on Spotify."
                else:
                    return f"Could not find {query} on Spotify."
            else:
                self.sp.start_playback(device_id=device_id)
                return "Resumed playback on Spotify."
        except Exception as e:
            return f"Error playing music: {e}"

    def pause_music(self):
        if not self.enabled:
            return "Spotify is not enabled."
        try:
            self.sp.pause_playback()
            return "Paused Spotify playback."
        except Exception as e:
            return f"Error pausing music: {e}"

    def next_track(self):
        if not self.enabled:
            return "Spotify is not enabled."
        try:
            self.sp.next_track()
            return "Skipped to next track."
        except Exception as e:
            return f"Error skipping track: {e}"
