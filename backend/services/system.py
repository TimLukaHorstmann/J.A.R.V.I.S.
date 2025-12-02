import os
import platform
import logging

logger = logging.getLogger("jarvis.system")

class SystemService:
    def __init__(self):
        self.os_type = platform.system()

    def set_volume(self, level: int):
        """Sets the system volume (0-100)."""
        if self.os_type == "Darwin":
            # macOS
            osascript_cmd = f"set volume output volume {level}"
            os.system(f"osascript -e '{osascript_cmd}'")
            return f"Volume set to {level}%."
        else:
            return "Volume control only supported on macOS for now."

    def get_battery_status(self):
        if self.os_type == "Darwin":
            try:
                # Simple check using pmset
                stream = os.popen('pmset -g batt')
                output = stream.read()
                return output.strip()
            except Exception as e:
                return f"Error getting battery status: {e}"
        return "Battery status not supported on this OS."
