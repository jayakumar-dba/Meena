"""
Run this to verify your bot token is working.
Usage: python3 verify_bot.py
"""
import requests
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("WEBEX_BOT_TOKEN")

rooms = requests.get(
    "https://webexapis.com/v1/rooms",
    headers={"Authorization": f"Bearer {TOKEN}"},
    params={"max": 20}
).json().get("items", [])

print("\n✅ Bot can see these rooms:")
print("-" * 70)
for r in rooms:
    print(f"  {r.get('title', 'N/A'):<40} {r['id']}")

if not rooms:
    print("  ⚠️  No rooms found. Add the bot to your group chat first.")
