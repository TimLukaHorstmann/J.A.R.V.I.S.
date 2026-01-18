import json
import logging
import asyncio
import websockets
import aiohttp
from typing import Dict, Any, Callable

logger = logging.getLogger("jarvis.eufy")

class EufyService:
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("eufy", {})
        self.ws_url = self.config.get("ws_url", "ws://localhost:3000")
        self.go2rtc_api = self.config.get("go2rtc", {}).get("api_url", "http://localhost:1984/api")
        self.go2rtc_stream_base = self.config.get("go2rtc", {}).get("stream_url", "http://localhost:1984/stream.html")
        
        # Determine if enabled: check top-level tools config OR eufy section
        tools_config = config.get("tools", {})
        self.enabled = tools_config.get("eufy", False) or self.config.get("enabled", False)
        
        self.ws = None
        self.devices = {}
        self.connected = False
        self._pending_requests = {}
        self._callback: Callable = None

    async def initialize(self):
        if not self.enabled:
            logger.info("Eufy service disabled in config")
            return

        asyncio.create_task(self._connect_loop())

    async def _connect_loop(self):
        while True:
            try:
                logger.info(f"Connecting to Eufy WS at {self.ws_url}...")
                async with websockets.connect(self.ws_url) as websocket:
                    self.ws = websocket
                    self.connected = True
                    logger.info("✅ Connected to Eufy Security WS")
                    
                    # Start listening
                    await self._send_command("start_listening")
                    await self._send_command("set_api_schema", schemaVersion=15)
                    await self._update_devices()
                    
                    async for message in self.ws:
                        data = json.loads(message)
                        await self._handle_message(data)
                        
            except Exception as e:
                logger.error(f"Eufy WS connection error: {e}")
                self.connected = False
                self.ws = None
                # Fail all pending requests
                for fut in self._pending_requests.values():
                    if not fut.done():
                        fut.set_exception(e)
                self._pending_requests.clear()
            
            await asyncio.sleep(10)

    async def _handle_message(self, data: dict):
        msg_type = data.get("type")
        msg_id = data.get("messageId")
        
        # Cache state from ANY result that contains state+devices
        result = data.get("result", {})
        if isinstance(result, dict) and "state" in result:
            state = result["state"]
            
            # Store stations separately for reference
            if "stations" in state and isinstance(state["stations"], list):
                for station in state["stations"]:
                    serial = station.get("serialNumber")
                    if serial:
                        self.devices[serial] = station
            
            # Store camera devices
            if "devices" in state and isinstance(state["devices"], list):
                # Store devices from state (devices is an array, not a dict)
                # Clear previous camera devices but keep stations
                camera_serials = []
                for device in state["devices"]:
                    serial = device.get("serialNumber")
                    if serial:
                        self.devices[serial] = device
                        camera_serials.append(serial)
                
                # Count only cameras (not stations)
                camera_count = len([d for d in self.devices.values() if d.get("model", "").startswith("T8")])
                logger.info(f"✅ Cached {camera_count} Eufy devices")
        
        # Handle command responses
        if msg_id and msg_id in self._pending_requests:
            future = self._pending_requests[msg_id]
            if msg_type == "result":
                if data.get("success"):
                    future.set_result(data.get("result"))
                else:
                    future.set_exception(Exception(f"Eufy Error: {data.get('errorCode')}"))
                del self._pending_requests[msg_id]
        
        # Handle events
        if msg_type == "event":
            event = data.get("event", {})
            event_type = event.get("event")
            
            if event_type == "got rtsp url":
                 if self._callback:
                     await self._callback("rtsp_url", event)
            
            # Auto-update devices on property changes if needed
            # For now, minimal.

    async def _send_command(self, command: str, wait_for_result=False, **kwargs):
        if not self.ws:
            if wait_for_result:
                raise ConnectionError("Not connected to Eufy WS")
            return

        msg_id = f"jarvis-{int(asyncio.get_event_loop().time() * 1000)}"
        payload = {
            "messageId": msg_id,
            "command": command,
            **kwargs
        }
        
        future = None
        if wait_for_result:
            future = asyncio.get_event_loop().create_future()
            self._pending_requests[msg_id] = future

        await self.ws.send(json.dumps(payload))
        
        if wait_for_result:
            return await asyncio.wait_for(future, timeout=10)

    async def _update_devices(self):
        try:
            # According to schema, we want to get stations and devices
            # But simplest is usually just listing them via driver properties?
            # Or use 'driver.get_devices' if available. 
            # In bropat/eufy-security-ws, usually we rely on getting a text list manually 
            # or handling the 'start_listening' initial dump.
            pass
        except Exception:
            pass

    async def get_devices(self):
        """
        Returns a list of camera devices from cached state (excludes stations).
        """
        try:
            devices = []
            for serial, device_data in self.devices.items():
                # Filter out stations (T8030 models) - only return cameras
                model = device_data.get("model", "")
                if model.startswith("T8030"):  # Skip HomeBase stations
                    continue
                    
                # All camera devices from Eufy (T8160-C is SoloCam, etc.)
                devices.append({
                    "name": device_data.get("name", f"Camera {serial}"),
                    "serial": serial,
                    "model": model,
                    "station": device_data.get("stationSerialNumber"),
                    "battery": device_data.get("battery"),
                    "enabled": device_data.get("enabled"),
                    "connected": device_data.get("state") == 1
                })
            return devices
        except Exception as e:
            logger.error(f"Failed to get devices: {e}")
            return []

    async def start_stream(self, serial: str) -> str:
        """
        Starts a stream and returns a Web-viewable URL (via go2rtc).
        For T8160-C SoloCam models, RTSP must be enabled in the Eufy app first.
        """
        try:
            logger.info(f"Starting stream for device {serial}...")
            
            # First, verify device exists in our cache
            if serial not in self.devices:
                logger.error(f"Device {serial} not in cache. Available: {list(self.devices.keys())}")
                return f"Error: Device {serial} not found in cache."
            
            device = self.devices[serial]
            device_name = device.get("name", serial)
            model = device.get("model", "Unknown")
            rtsp_enabled = device.get("rtspStream", False)
            
            logger.info(f"Device: {device_name}, Model: {model}, RTSP: {rtsp_enabled}")
            
            # Check if RTSP is enabled
            if not rtsp_enabled:
                return (
                    f"⚠️ RTSP streaming is not enabled for '{device_name}'.\n\n"
                    f"To enable RTSP streaming:\n"
                    f"1. Open the Eufy Security app\n"
                    f"2. Select the '{device_name}' camera\n"
                    f"3. Go to Settings → Storage Settings\n"
                    f"4. Enable 'NAS (RTSP)'\n"
                    f"5. Try streaming again\n\n"
                    f"Note: RTSP streaming may drain battery faster on battery-powered cameras."
                )
            
            # Check if stream is already configured in go2rtc
            stream_name = f"eufy_{device_name.lower().replace(' ', '_').replace('ü', 'u').replace('ö', 'o').replace('ä', 'a')}"
            
            # Query go2rtc to see if this stream exists
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{self.go2rtc_api}/streams") as resp:
                        if resp.status == 200:
                            streams = await resp.json()
                            if stream_name in streams:
                                logger.info(f"Stream {stream_name} found in go2rtc")
                                # Return the viewer URL
                                return f"{self.go2rtc_stream_base}?src={stream_name}"
            except Exception as e:
                logger.warning(f"Could not query go2rtc streams: {e}")
            
            # Stream not found in go2rtc - provide setup instructions
            station_serial = device.get("stationSerialNumber")
            if station_serial and station_serial in self.devices:
                station = self.devices[station_serial]
            else:
                # Try to find station in our devices
                station = None
                for dev_serial, dev_data in self.devices.items():
                    if dev_data.get("model", "").startswith("T8030"):  # Station model
                        station = dev_data
                        break
            
            if not station:
                return "Error: Could not find HomeBase station information."
            
            station_ip = station.get("lanIpAddress", "192.168.1.120")
            
            return (
                f"⚠️ Stream not configured in go2rtc for '{device_name}'.\n\n"
                f"To set up streaming:\n"
                f"1. Add this to backend/go2rtc.yaml under 'streams:':\n"
                f"   {stream_name}: rtsp://USERNAME:PASSWORD@{station_ip}:8554/liveX\n\n"
                f"2. Replace USERNAME (usually 'admin') and PASSWORD with your RTSP credentials\n"
                f"3. Replace X with the camera channel (0, 1, or 2)\n"
                f"4. Restart go2rtc: pkill -f go2rtc && ./backend/start_go2rtc.sh\n"
                f"5. Try streaming again"
            )
           
        except Exception as e:
            logger.error(f"Stream start error: {e}", exc_info=True)
            return f"Error starting stream: {e}"

    async def add_stream_to_go2rtc(self, name: str, source_url: str):
        url = f"{self.go2rtc_api}/streams"
        params = {"src": source_url, "name": name}
        async with aiohttp.ClientSession() as session:
            async with session.put(url, params=params) as resp:
                if resp.status not in [200, 201]:
                    logger.error(f"Go2RTC Error: {await resp.text()}")

