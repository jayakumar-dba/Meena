"""
Run this ONCE to find your Webex Room ID.
Usage: python3 get_room_id.py
"""
import requests
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("WEBEX_BOT_TOKEN")

r = requests.get(
    "https://webexapis.com/v1/rooms",
    headers={"Authorization": f"Bearer {TOKEN}"},
    params={"max": 20}
)

rooms = r.json().get("items", [])
print(f"\n{'#':<4} {'ROOM TITLE':<45} {'ROOM ID'}")
print("-" * 100)
for i, room in enumerate(rooms, 1):
    print(f"{i:<4} {room.get('title', 'Direct Message'):<45} {room['id']}")

print("\n👆 Copy the Room ID that matches your regression report group chat")
