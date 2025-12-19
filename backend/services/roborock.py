import asyncio
import logging
import json
import pathlib
import dataclasses
from typing import Any, Dict, Optional
import dotenv

# Try importing python-roborock, handle if not installed
try:
    from roborock.web_api import RoborockApiClient
    from roborock.devices.device_manager import create_device_manager
    from roborock.devices.file_cache import FileCache, load_value, store_value
    from roborock import RoborockCommand
    ROBOROCK_AVAILABLE = True
except ImportError:
    ROBOROCK_AVAILABLE = False
    # Define dummy class for type hinting if import fails
    class RoborockCommand:
        pass

logger = logging.getLogger("jarvis.roborock")

USER_PARAMS_PATH = pathlib.Path.home() / ".cache" / "jarvis" / "roborock-user-params.pkl"
CACHE_PATH = pathlib.Path.home() / ".cache" / "jarvis" / "roborock-cache-data.pkl"

# Ensure cache directory exists
USER_PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)

class RoborockService:
    def __init__(self, config: Dict[str, Any]):
        self.username = dotenv.get_key("../.env", "ROBOROCK_USERNAME")
        self.enabled = ROBOROCK_AVAILABLE and bool(self.username)
        self.device_manager = None
        self.web_api = None
        
        if not ROBOROCK_AVAILABLE:
            logger.warning("python-roborock not installed. Roborock service disabled.")
        elif not self.username:
            logger.warning("Roborock credentials not found. Service disabled.")
        else:
            logger.info("Roborock service initialized.")

    def _run_async(self, coro):
        """Helper to run async methods synchronously."""
        try:
            return asyncio.run(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)

    async def request_login_code(self):
        """Request a login code to be sent to the email."""
        if not self.username:
            return "Username not configured."
        self.web_api = RoborockApiClient(username=self.username)
        await self.web_api.request_code()
        return f"Login code sent to {self.username}. Please use the 'submit_login_code' tool with the code you received."

    async def submit_login_code(self, code: str):
        """Submit the login code to complete authentication."""
        if not self.web_api:
            self.web_api = RoborockApiClient(username=self.username)
        
        try:
            user_data = await self.web_api.code_login(code)
            
            from roborock.devices.device_manager import UserParams
            
            user_params = UserParams(
                username=self.username,
                user_data=user_data,
            )
            
            await store_value(USER_PARAMS_PATH, user_params)
            return "Login successful. Credentials cached."
        except Exception as e:
            return f"Login failed: {e}"

    async def _get_device_manager(self):
        if self.device_manager:
            return self.device_manager

        user_params = await load_value(USER_PARAMS_PATH)
        if user_params is None:
            raise Exception("Not logged in. Please ask me to 'login to Roborock' first.")
            
        cache = FileCache(CACHE_PATH)
        self.device_manager = await create_device_manager(user_params, cache=cache)
        return self.device_manager

    async def _get_first_device(self):
        dm = await self._get_device_manager()
        devices = await dm.get_devices()
        if not devices:
            raise Exception("No devices found.")
        return devices[0]

    async def _send_command(self, command: RoborockCommand, params: Any = None):
        device = await self._get_first_device()
        
        # Try to use v1_properties.command.send (as seen in roborock_test.py)
        if hasattr(device, 'v1_properties') and hasattr(device.v1_properties, 'command') and hasattr(device.v1_properties.command, 'send'):
             return await device.v1_properties.command.send(command, params)

        # Try to use send_command if available, otherwise fallback to async_send_command
        if hasattr(device, 'send_command'):
            return await device.send_command(command, params)
        elif hasattr(device, 'async_send_command'):
             return await device.async_send_command(command, params)
        else:
            raise Exception("Device object does not support direct command sending.")

    def request_code(self):
        if not self.enabled: return "Service disabled"
        return self._run_async(self.request_login_code())

    def submit_code(self, code):
        if not self.enabled: return "Service disabled"
        return self._run_async(self.submit_login_code(code))

    def start_cleaning(self):
        if not self.enabled: return "Service disabled"
        try:
            self._run_async(self._send_command(RoborockCommand.APP_START))
            return "Cleaning started."
        except Exception as e:
            return f"Failed to start cleaning: {e}"

    def pause_cleaning(self):
        if not self.enabled: return "Service disabled"
        try:
            self._run_async(self._send_command(RoborockCommand.APP_PAUSE))
            return "Cleaning paused."
        except Exception as e:
            return f"Failed to pause cleaning: {e}"

    def return_to_dock(self):
        if not self.enabled: return "Service disabled"
        try:
            self._run_async(self._send_command(RoborockCommand.APP_CHARGE))
            return "Returning to dock."
        except Exception as e:
            return f"Failed to return to dock: {e}"

    def get_status(self):
        if not self.enabled: return "Service disabled"
        try:
            status = self._run_async(self._send_command(RoborockCommand.GET_STATUS))
            return json.dumps(status, default=str)
        except Exception as e:
            return f"Failed to get status: {e}"
            
    def start_wash(self):
        if not self.enabled: return "Service disabled"
        try:
            cmd = getattr(RoborockCommand, 'APP_START_WASH', 'app_start_wash')
            self._run_async(self._send_command(cmd))
            return "Mop washing started."
        except Exception as e:
            return f"Failed to start mop washing: {e}"

    def start_empty_bin(self):
        if not self.enabled: return "Service disabled"
        try:
            cmd = getattr(RoborockCommand, 'APP_START_COLLECT_DUST', 'app_start_collect_dust')
            self._run_async(self._send_command(cmd))
            return "Dust collection started."
        except Exception as e:
            return f"Failed to start dust collection: {e}"

    def get_rooms(self):
        if not self.enabled: return "Service disabled"
        try:
            cmd = getattr(RoborockCommand, 'GET_ROOM_MAPPING', 'get_room_mapping')
            rooms = self._run_async(self._send_command(cmd))
            return json.dumps(rooms)
        except Exception as e:
            return f"Failed to get rooms: {e}"

    def clean_rooms(self, room_ids):
        if not self.enabled: return "Service disabled"
        try:
            # Use simple list of IDs as per roborock_test.py
            cmd = getattr(RoborockCommand, 'APP_SEGMENT_CLEAN', 'app_segment_clean')
            self._run_async(self._send_command(cmd, room_ids))
            return f"Started cleaning rooms: {room_ids}"
        except Exception as e:
            return f"Failed to clean rooms: {e}"

    def clean_room_by_name(self, room_name: str):
        if not self.enabled: return "Service disabled"
        try:
            from services.room_mapping import ROOMS
        except ImportError:
            return "Room mapping not found."
        
        # Case insensitive lookup
        room_id = None
        for name, r_id in ROOMS.items():
            if name.lower() == room_name.lower():
                room_id = r_id
                break
        
        if room_id is None:
            return f"Room '{room_name}' not found. Available rooms: {', '.join(ROOMS.keys())}"
            
        return self.clean_rooms([room_id])

    def find_robot(self):
        if not self.enabled: return "Service disabled"
        try:
            cmd = getattr(RoborockCommand, 'FIND_ME', 'find_me')
            self._run_async(self._send_command(cmd))
            return "Playing 'Find Me' sound."
        except Exception as e:
            return f"Failed to find robot: {e}"

    def stop_cleaning(self):
        if not self.enabled: return "Service disabled"
        try:
            cmd = getattr(RoborockCommand, 'APP_STOP', 'app_stop')
            self._run_async(self._send_command(cmd))
            return "Cleaning stopped."
        except Exception as e:
            return f"Failed to stop cleaning: {e}"
            
    def set_mode(self, mode):
        if not self.enabled: return "Service disabled"
        try:
            cmd_custom = getattr(RoborockCommand, 'SET_CUSTOM_MODE', 'set_custom_mode')
            cmd_water = getattr(RoborockCommand, 'SET_WATER_BOX_CUSTOM_MODE', 'set_water_box_custom_mode')
            cmd_mop = getattr(RoborockCommand, 'SET_MOP_MODE', 'set_mop_mode')
            
            if mode == "vacuum":
                self._run_async(self._send_command(cmd_custom, [102]))
                self._run_async(self._send_command(cmd_water, [200]))
                self._run_async(self._send_command(cmd_mop, [300]))
            elif mode == "mop":
                self._run_async(self._send_command(cmd_mop, [301]))
            elif mode == "both":
                self._run_async(self._send_command(cmd_mop, [300]))
                self._run_async(self._send_command(cmd_custom, [102]))
                self._run_async(self._send_command(cmd_water, [201]))
            else:
                return "Unknown mode. Use 'vacuum', 'mop', or 'both'."
            return f"Set mode to {mode}"
        except Exception as e:
            return f"Failed to set mode: {e}"
