import logging
import json
import threading
import time
try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

logger = logging.getLogger("jarvis.openwb")

class OpenWBService:
    def __init__(self, config):
        self.config = config.get("openwb", {})
        self.ip = self.config.get("ip", "openwb.local")
        self.enabled = self.config.get("enabled", False)
        self.state = {}
        self.client = None
        self.thread = None
        self.connected = False

        if not mqtt:
            logger.warning("paho-mqtt not installed. OpenWB service disabled.")
            self.enabled = False
            return

        if self.enabled:
            self._start_client()

    def _start_client(self):
        try:
            self.client = mqtt.Client()
            self.client.on_connect = self.on_connect
            self.client.on_message = self.on_message
            self.client.on_disconnect = self.on_disconnect
            
            # Start background thread to manage connection
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
        except Exception as e:
            logger.error(f"Failed to initialize OpenWB MQTT client: {e}")

    def _run_loop(self):
        while self.enabled:
            try:
                if not self.connected:
                    logger.info(f"Connecting to OpenWB MQTT broker at {self.ip}...")
                    self.client.connect(self.ip, 1883, 60)
                    self.client.loop_start()
                    self.connected = True
                time.sleep(10)
            except Exception as e:
                logger.error(f"Error in OpenWB connection loop: {e}")
                self.connected = False
                time.sleep(30)

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to OpenWB MQTT broker")
            # Subscribe to all openWB topics
            client.subscribe("openWB/#")
        else:
            logger.error(f"Failed to connect to OpenWB MQTT broker with code {rc}")
            self.connected = False

    def on_disconnect(self, client, userdata, rc):
        logger.warning("Disconnected from OpenWB MQTT broker")
        self.connected = False

    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8")
            
            # Filter out 'set' topics to avoid confusion, though we only read anyway
            # Exception: openWB/counter/set/home_consumption is the correct topic for house consumption in 2.0
            if "/set/" in topic and "home_consumption" not in topic:
                return

            # Store in state
            self.state[topic] = payload
            
            # Debug log for first few messages to verify structure
            if len(self.state) < 20:
                logger.debug(f"MQTT received: {topic} = {payload}")
                
        except Exception as e:
            logger.debug(f"Error processing MQTT message: {e}")

    def _format_power(self, power):
        if power is None:
            return "0 W"
        try:
            power = float(power)
            if abs(power) >= 1000:
                return f"{power/1000:.2f} kW"
            return f"{power:.0f} W"
        except (ValueError, TypeError):
            return "0 W"

    def get_status(self):
        """
        Returns a simplified status object for the agent.
        """
        if not self.enabled or not self.connected:
            return {"error": "OpenWB service is not connected or disabled."}

        # Debug: Log available topics if charge points are missing
        charge_point_topics = [k for k in self.state.keys() if "chargepoint" in k or "lp" in k]
        if not charge_point_topics:
             logger.info(f"No chargepoint topics found. Total topics: {len(self.state)}")
             # Log a sample of topics to help debug
             logger.info(f"Sample topics: {list(self.state.keys())[:10]}")

        # Extract key metrics to avoid overwhelming the LLM with thousands of MQTT topics
        # Try OpenWB 2.0 structure first, then fallback to 1.9
        
        # PV Power
        # OpenWB 2.0: openWB/pv/get/power (Negative = Generation usually, but sometimes positive depending on config)
        pv_power = self._get_value("openWB/pv/get/power", None, float)
        if pv_power is None:
            pv_power = self._get_value("openWB/pv/W", 0, float) # 1.9
        
        # Invert PV power if it's negative (User request)
        if pv_power is not None and pv_power < 0:
            pv_power = abs(pv_power)

        # Grid Power
        # OpenWB 2.0: openWB/counter/0/get/power (Main meter)
        grid_power = self._get_value("openWB/global/get/grid_power", None, float)
        if grid_power is None:
            grid_power = self._get_value("openWB/counter/0/get/power", None, float)
        if grid_power is None:
            grid_power = self._get_value("openWB/evu/W", 0, float) # 1.9

        # House Consumption
        # OpenWB 2.0: openWB/counter/set/home_consumption (Calculated value)
        house_consumption = self._get_value("openWB/global/get/house_consumption", None, float)
        if house_consumption is None:
            house_consumption = self._get_value("openWB/counter/set/home_consumption", None, float)
        if house_consumption is None:
            house_consumption = self._get_value("openWB/global/Hausverbrauch", 0, float) # 1.9

        status = {
            "pv_power": pv_power,
            "pv_power_formatted": self._format_power(pv_power),
            "house_consumption": house_consumption,
            "house_consumption_formatted": self._format_power(house_consumption),
            "grid_power": grid_power,
            "grid_power_formatted": self._format_power(grid_power),
            "charge_points": []
        }

        # Try to find charge points (OpenWB 2.0)
        found_cp = False
        # OpenWB 2.0 usually uses chargepoint/X
        # Based on debug, we saw chargepoint/3/get/power (not power_all)
        for i in range(0, 10): 
            # Check for power topic (it was 'power' in debug, not 'power_all')
            if f"openWB/chargepoint/{i}/get/power" in self.state:
                found_cp = True
                cp = {
                    "id": i,
                    "power": self._get_value(f"openWB/chargepoint/{i}/get/power", 0, float),
                    "power_formatted": self._format_power(self._get_value(f"openWB/chargepoint/{i}/get/power", 0, float)),
                    "plugged": self._get_value(f"openWB/chargepoint/{i}/get/plug_state", 0, str) == "true", # Debug showed "true" string or boolean? MQTT payload is string "true" usually
                    "charging": self._get_value(f"openWB/chargepoint/{i}/get/charge_state", 0, str) == "true",
                    "soc": self._get_value(f"openWB/vehicle/{i}/get/soc", 0, int),
                    "name": self._get_value(f"openWB/vehicle/{i}/name", f"Vehicle {i}")
                }
                # Fix boolean parsing if it comes as "true"/"false" string
                if isinstance(self.state.get(f"openWB/chargepoint/{i}/get/plug_state"), str):
                     cp["plugged"] = self.state.get(f"openWB/chargepoint/{i}/get/plug_state").lower() == "true"
                if isinstance(self.state.get(f"openWB/chargepoint/{i}/get/charge_state"), str):
                     cp["charging"] = self.state.get(f"openWB/chargepoint/{i}/get/charge_state").lower() == "true"
                
                status["charge_points"].append(cp)
        
        # Fallback to OpenWB 1.9 if no 2.0 chargepoints found
        if not found_cp:
            # OpenWB 1.9 uses lp/X
            for i in range(1, 9):
                # Check if the topic exists in the state keys
                # We need to be careful about exact topic matching
                if f"openWB/lp/{i}/W" in self.state:
                    cp = {
                        "id": i,
                        "power": self._get_value(f"openWB/lp/{i}/W", 0, float),
                        "power_formatted": self._format_power(self._get_value(f"openWB/lp/{i}/W", 0, float)),
                        "plugged": self._get_value(f"openWB/lp/{i}/boolPlugStat", 0, int) == 1,
                        "charging": self._get_value(f"openWB/lp/{i}/boolChargeStat", 0, int) == 1,
                        "soc": self._get_value(f"openWB/lp/{i}/%Soc", 0, int),
                        "name": f"Loadpoint {i}" 
                    }
                    status["charge_points"].append(cp)

        return status

    def _get_value(self, topic, default, type_cast=str):
        val = self.state.get(topic)
        if val is None:
            return default
        try:
            return type_cast(val)
        except ValueError:
            return default
