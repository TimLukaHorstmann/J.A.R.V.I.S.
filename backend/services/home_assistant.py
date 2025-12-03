import requests
import logging
import os

logger = logging.getLogger("jarvis.home_assistant")

class HomeAssistantService:
    def __init__(self, config):
        self.config = config.get("home_assistant", {})
        
        # Prioritize environment variables over config file for security and overrides
        self.base_url = os.getenv("HASS_URL") or self.config.get("url")
        self.token = os.getenv("HASS_TOKEN") or self.config.get("token")
        
        # Enable if explicitly enabled in config OR if credentials are provided in env
        config_enabled = self.config.get("enabled", False)
        has_credentials = bool(self.base_url and self.token)
        
        self.enabled = config_enabled or has_credentials
        
        if self.enabled and not has_credentials:
            logger.warning("Home Assistant enabled but URL or Token missing. Disabling.")
            self.enabled = False
        
        if self.enabled:
            # Normalize URL
            if self.base_url.endswith("/"):
                self.base_url = self.base_url[:-1]
            logger.info(f"Home Assistant service initialized at {self.base_url}")

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def get_state(self, entity_id):
        if not self.enabled:
            return "Home Assistant is not enabled."
        try:
            url = f"{self.base_url}/api/states/{entity_id}"
            response = requests.get(url, headers=self._headers(), timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return f"Error getting state for {entity_id}: {e}"

    def call_service(self, domain, service, service_data=None):
        if not self.enabled:
            return "Home Assistant is not enabled."
        try:
            url = f"{self.base_url}/api/services/{domain}/{service}"
            response = requests.post(url, headers=self._headers(), json=service_data or {}, timeout=5)
            response.raise_for_status()
            return f"Service {domain}.{service} called successfully."
        except Exception as e:
            return f"Error calling service {domain}.{service}: {e}"

    def turn_on(self, entity_id):
        return self.call_service("homeassistant", "turn_on", {"entity_id": entity_id})

    def turn_off(self, entity_id):
        return self.call_service("homeassistant", "turn_off", {"entity_id": entity_id})
