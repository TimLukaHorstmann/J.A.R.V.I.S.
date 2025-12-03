import requests
import logging
import os
import json

logger = logging.getLogger("jarvis.home_assistant")

class HomeAssistantService:
    def __init__(self, config):
        self.config = config.get("home_assistant", {})
        self.url = self.config.get("url") or os.getenv("HASS_URL") or "http://localhost:8123"
        self.url = self.url.rstrip("/")
        self.token = self.config.get("token") or os.getenv("HASS_TOKEN") or os.getenv("HA_TOKEN")
        self.enabled = False
        
        if self.token:
            self.headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
            self.enabled = True
            logger.info(f"Home Assistant service initialized at {self.url}")
        else:
            logger.warning("Home Assistant token not found. Service disabled.")

    def _post(self, endpoint, data=None):
        if not self.enabled:
            raise RuntimeError("Home Assistant service is not enabled.")
        
        url = f"{self.url}/api/{endpoint}"
        try:
            response = requests.post(url, headers=self.headers, json=data, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error calling Home Assistant API {endpoint}: {e}")
            raise

    def get_alexa_devices(self):
        """
        Returns a dictionary mapping device names to device IDs.
        """
        if not self.enabled:
            return {}

        # Template to generate a JSON object of "Device Name": "Device ID"
        template = """
        {
        {% for d in integration_entities('alexa_devices')| map('device_id') | unique | list %}
        "{{ device_name(d) }}": "{{ d }}"{{ "," if not loop.last else "" }}
        {% endfor %}
        }
        """
        try:
            # Render the template
            res = self._post("template", {"template": template})
            # The result is a string containing the rendered JSON
            if isinstance(res, str):
                return json.loads(res)
            elif isinstance(res, dict):
                 # Sometimes HA might return a dict if the template is simple? 
                 # Usually /api/template returns the rendered string as text/plain if not requested otherwise,
                 # but requests.post(...).json() might fail if it's not JSON.
                 # Wait, /api/template returns text.
                 pass
            
            # Let's re-check how _post handles response.
            # response.json() will fail if the response is plain text.
            # /api/template returns text/plain.
            
            return {}
        except Exception as e:
            logger.error(f"Failed to get Alexa devices: {e}")
            return {}

    def _render_template(self, template_str):
        """
        Helper to render a template and return the string result.
        """
        if not self.enabled:
            return None
            
        url = f"{self.url}/api/template"
        try:
            response = requests.post(url, headers=self.headers, json={"template": template_str}, timeout=10)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Error rendering template: {e}")
            return None

    def get_alexa_devices_safe(self):
        """
        Returns a dictionary mapping device names to device IDs using the text rendering method.
        """
        template = """
        {
        {% for d in integration_entities('alexa_devices')| map('device_id') | unique | list %}
        "{{ device_name(d) }}": "{{ d }}"{{ "," if not loop.last else "" }}
        {% endfor %}
        }
        """
        json_str = self._render_template(template)
        if json_str:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse device list JSON: {json_str}")
        return {}

    def resolve_device(self, device_name_or_id):
        """
        Helper to resolve a name to an ID. If it looks like an ID, return it.
        Otherwise try to find it in the device list.
        """
        # If it looks like a long hex string (32 chars), assume it's an ID
        if len(device_name_or_id) == 32 and " " not in device_name_or_id:
             return device_name_or_id
             
        devices = self.get_alexa_devices_safe()
        
        # Try exact match
        if device_name_or_id in devices:
            return devices[device_name_or_id]
        
        # Try case-insensitive match
        lower_name = device_name_or_id.lower()
        for name, dev_id in devices.items():
            if name.lower() == lower_name:
                return dev_id
                
        # Try partial match
        for name, dev_id in devices.items():
            if lower_name in name.lower():
                return dev_id
                
        return None

    def send_text_command(self, device_name_or_id, command):
        device_id = self.resolve_device(device_name_or_id)
        if not device_id:
            return f"Could not find Alexa device '{device_name_or_id}'."
            
        data = {
            "device_id": device_id,
            "text_command": command
        }
        try:
            self._post("services/alexa_devices/send_text_command", data)
            return f"Sent command '{command}' to device {device_id}."
        except Exception as e:
            return f"Error sending command: {e}"

    def play_sound(self, device_name_or_id, sound):
        device_id = self.resolve_device(device_name_or_id)
        if not device_id:
            return f"Could not find Alexa device '{device_name_or_id}'."
            
        data = {
            "device_id": device_id,
            "sound": sound
        }
        try:
            self._post("services/alexa_devices/send_sound", data)
            return f"Played sound '{sound}' on device {device_id}."
        except Exception as e:
            return f"Error playing sound: {e}"
