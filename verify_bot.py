"""
Run this to verify your bot token is working.
Usage: python3 verify_bot.py
"""
import requests
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("WEBEX_TOKEN") or os.getenv("WEBEX_ACCESS_TOKEN") or os.getenv("WEBEX_BOT_TOKEN")

if not TOKEN:
    raise SystemExit("❌ Missing Webex token. Set WEBEX_TOKEN or WEBEX_ACCESS_TOKEN (WEBEX_BOT_TOKEN is also supported).")

response = requests.get(
    "https://webexapis.com/v1/rooms",
    headers={"Authorization": f"Bearer {TOKEN}"},
    params={"max": 20},
    timeout=15,
)
if response.status_code == 401:
    raise SystemExit("❌ Webex token is invalid/expired (401 Unauthorized).")
response.raise_for_status()
rooms = response.json().get("items", [])

print("\n✅ Bot can see these rooms:")
print("-" * 70)
for r in rooms:
    print(f"  {r.get('title', 'N/A'):<40} {r['id']}")

if not rooms:
    print("  ⚠️  No rooms found. Add the bot to your group chat first.")
