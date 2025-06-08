# ais_worker.py
from PyQt5.QtCore import QObject, pyqtSignal
import asyncio
import websockets
import json

class AISWorker(QObject):
    vessel_received = pyqtSignal(str, float, float)  # mmsi, lat, lon

    def __init__(self, mmsi_list, api_key, parent=None):
        """
        The worker now accepts the API key as an argument.
        """
        super().__init__(parent)
        self.mmsi_list = mmsi_list
        self.api_key = api_key  # Store the API key
        self.running = True

    async def connect_ais_stream(self):
        """
        Connects to the AIS stream using the provided API key.
        """
        # Do not proceed if the API key is missing.
        if not self.api_key:
            print("AIS Worker: API Key is missing. Aborting connection.")
            return

        async with websockets.connect("wss://stream.aisstream.io/v0/stream") as websocket:
            subscribe_message = {
                "APIKey": self.api_key,  # Use the API key from the constructor
                "BoundingBoxes": [[[-90, -180], [90, 180]]], # World
                "FiltersShipMMSI": self.mmsi_list,
                "FilterMessageTypes": ["PositionReport"]
            }

            await websocket.send(json.dumps(subscribe_message))

            async for message_json in websocket:
                if not self.running:
                    break
                message = json.loads(message_json)
                # Add a check for error messages from the server (e.g., invalid API key)
                if message.get("MessageType") == "ErrorMessage":
                    print(f"AIS Stream Error: {message.get('Message')}")
                    break
                
                if message.get("MessageType") == "PositionReport":
                    msg = message["Message"]["PositionReport"]
                    mmsi = str(msg["UserID"])
                    lat = msg["Latitude"]
                    lon = msg["Longitude"]
                    self.vessel_received.emit(mmsi, lat, lon)

    def run(self):
        """
        Runs the asyncio event loop to connect to the stream.
        """
        try:
            asyncio.run(self.connect_ais_stream())
        except Exception as e:
            # Log any exceptions that occur during connection or streaming
            print(f"AIS Worker Error: {e}")

    def stop(self):
        """
        Stops the worker loop.
        """
        self.running = False
