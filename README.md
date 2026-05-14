# Regression Dashboard

Automated regression report dashboard that reads from Webex group chat.

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/jayakumar-dba/Meena.git
cd Meena

# 2. Install dependencies
pip3 install -r requirements.txt

# 3. Create .env file
cp .env.example .env
# Edit .env and fill in your WEBEX_TOKEN (or WEBEX_ACCESS_TOKEN) and WEBEX_ROOM_ID

# 4. Get your Room ID (run once)
python3 get_room_id.py

# 5. Pull data from Webex
python3 collector.py
# You can also choose a specific range non-interactively:
# python3 collector.py --range today
# python3 collector.py --days 7

# 6. Start dashboard
python3 dashboard.py
# Open http://localhost:5000
```
