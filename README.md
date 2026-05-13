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
# Edit .env and fill in your WEBEX_BOT_TOKEN and WEBEX_ROOM_ID
# Optional: set GITLAB_PROJECT_URL to auto-build pipeline/job URLs from numeric IDs

# 4. Get your Room ID (run once)
python3 get_room_id.py

# 5. Pull data from Webex
python3 collector.py

# 6. Start dashboard
python3 dashboard.py
# Open http://localhost:5000

# If 5000 is busy:
python3 dashboard.py --port 5001
```
