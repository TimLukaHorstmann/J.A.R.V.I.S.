#!/usr/bin/env python3
"""Test Eufy WebSocket connection and list devices"""

import asyncio
import websockets
import json

async def test_eufy_ws():
    uri = "ws://localhost:3000"
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Connected to Eufy WS")
            
            # Send start_listening command
            msg1 = {
                "messageId": "test-1",
                "command": "start_listening"
            }
            await websocket.send(json.dumps(msg1))
            print(f"Sent: {msg1}")
            
            # Read responses for a few seconds
            try:
                while True:
                    response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    data = json.loads(response)
                    print(f"\nReceived: {json.dumps(data, indent=2)}")
                    
                    # If we get result for start_listening, try to get devices
                    if data.get("messageId") == "test-1" and data.get("type") == "result":
                        # Now try driver.get_devices
                        msg2 = {
                            "messageId": "test-2",
                            "command": "driver.get_devices"
                        }
                        await websocket.send(json.dumps(msg2))
                        print(f"\nSent: {msg2}")
                        
            except asyncio.TimeoutError:
                print("\n⏱️ No more messages (timeout)")
                
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_eufy_ws())
