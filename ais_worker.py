# ais_worker.py
from PyQt5.QtCore import QObject, QThread, pyqtSignal
import asyncio
import websockets
import json

# Replace this example API KEY with your key, you can get it for free from # https://aisstream.io/
API_KEY = "af5abf1c3ef9f7fbbb340b9a778187b7b46d8bc3"  # Example API Key, replace with your own

class AISWorker(QObject):
    vessel_received = pyqtSignal(str, float, float)  # mmsi, lat, lon

    def __init__(self, mmsi_name_map, parent=None):
        super().__init__(parent)
        self.mmsi_name_map = mmsi_name_map #["258647000"]
        self.running = True

    async def connect_ais_stream(self):
        async with websockets.connect("wss://stream.aisstream.io/v0/stream") as websocket:
            subscribe_message = {
                # Replace this example API KEY with your key, you can get it for free from # https://aisstream.io/
                "APIKey": API_KEY,  # Example API Key, replace with your own
                "BoundingBoxes": [[[-90, -180], [90, 180]]], # All vessels in the world
                "FiltersShipMMSI": self.mmsi_name_map,  # adjust as needed
                "FilterMessageTypes": ["PositionReport"]
            }

            await websocket.send(json.dumps(subscribe_message))

            async for message_json in websocket:
                if not self.running:
                    break
                message = json.loads(message_json)
                if message["MessageType"] == "PositionReport":
                    msg = message["Message"]["PositionReport"]
                    mmsi = str(msg["UserID"])
                    lat = msg["Latitude"]
                    lon = msg["Longitude"]
                    self.vessel_received.emit(mmsi, lat, lon)

    def run(self):
        asyncio.run(self.connect_ais_stream())

    def stop(self):
        self.running = False
