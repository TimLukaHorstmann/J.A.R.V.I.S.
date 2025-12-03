import paho.mqtt.client as mqtt
import time
import json

BROKER = "192.168.1.68"
TOPIC = "openWB/#"

messages = {}

def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    client.subscribe(TOPIC)

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode()
        messages[msg.topic] = payload
    except:
        pass

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

print(f"Connecting to {BROKER}...")
try:
    client.connect(BROKER, 1883, 60)
except Exception as e:
    print(f"Connection failed: {e}")
    exit(1)

client.loop_start()
print("Collecting messages for 5 seconds...")
time.sleep(5)
client.loop_stop()

print(f"\nCollected {len(messages)} topics.")

print("\n--- POWER Topics ---")
for t in sorted(messages.keys()):
    if "power" in t.lower() or "watt" in t.lower() or "/w" in t.lower():
        print(f"{t}: {messages[t]}")

print("\n--- SOC Topics ---")
for t in sorted(messages.keys()):
    if "soc" in t.lower():
        print(f"{t}: {messages[t]}")

print("\n--- PLUG/CHARGE STATE Topics ---")
for t in sorted(messages.keys()):
    if "plug" in t.lower() or "charge_state" in t.lower():
        print(f"{t}: {messages[t]}")
