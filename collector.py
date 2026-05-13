"""
Run this script to pull messages from your Webex group chat
and save execution summaries into a local SQLite database.

Usage:
    python3 collector.py
"""

import re
import sqlite3
import requests
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

WEBEX_TOKEN = os.getenv("WEBEX_BOT_TOKEN")
ROOM_ID     = os.getenv("WEBEX_ROOM_ID")
DB_FILE     = "regression.db"
HEADERS     = {"Authorization": f"Bearer {WEBEX_TOKEN}"}


# ── Database setup ────────────────────────────────────────────────────────────

def init_db():
    con = sqlite3.connect(DB_FILE)
    con.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id       TEXT UNIQUE,
            executed_at      TEXT,
            application      TEXT,
            env              TEXT,
            job_name         TEXT,
            ds_row           TEXT,
            source_branch    TEXT,
            triggered_by     TEXT,
            pipeline_id      TEXT,
            job_id           TEXT,
            scenarios_passed INTEGER DEFAULT 0,
            scenarios_failed INTEGER DEFAULT 0,
            pass_percent     REAL    DEFAULT 0,
            duration         TEXT,
            karate_url       TEXT,
            cluecumber_url   TEXT,
            cucumber_url     TEXT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS failures (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id     INTEGER,
            feature_file  TEXT,
            scenario_name TEXT,
            failure_line  TEXT,
            failure_reason TEXT,
            FOREIGN KEY(report_id) REFERENCES reports(id)
        )
    """)
    con.commit()
    con.close()
    print("✅ Database ready.")


# ── Webex polling ─────────────────────────────────────────────────────────────

def fetch_messages(max_msgs=100):
    url    = "https://webexapis.com/v1/messages"
    params = {"roomId": ROOM_ID, "max": max_msgs}
    r = requests.get(url, headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json().get("items", [])


# ── Message parser ────────────────────────────────────────────────────────────

def _get(text, key):
    """Extract value after 'Key:' up to next pipe or newline."""
    m = re.search(rf"{re.escape(key)}\s*[:\s]+([^|\n]+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def parse_message(msg):
    text = msg.get("text", "") or msg.get("markdown", "")

    # Only process execution summary messages
    if "Scenarios passed" not in text and "Execution summary" not in text:
        return None

    # Extract application from header
    app = ""
    header = re.search(r"Execution summary for pipeline\s*\|(.+)", text, re.IGNORECASE)
    if header:
        parts = [p.strip() for p in header.group(1).split("|")]
        app = parts[0] if parts else ""

    # Metrics line
    passed = re.search(r"passed[:\s]+(\d+)",    text, re.IGNORECASE)
    failed = re.search(r"failed[:\s]+(\d+)",    text, re.IGNORECASE)
    pct    = re.search(r"pass%[:\s]+([\d.]+)",  text, re.IGNORECASE)
    dur    = re.search(r"duration[:\s]+([\d\w\s]+)", text, re.IGNORECASE)

    # Report links
    links      = re.findall(r'https?://\S+', text)
    karate_url = next((l for l in links if "karate"     in l), "")
    clue_url   = next((l for l in links if "cluecumber" in l.lower()), "")
    cuke_url   = next((l for l in links if "cucumber"   in l.lower() and "karate" not in l), "")

    return {
        "message_id":       msg["id"],
        "executed_at":      msg.get("created", datetime.utcnow().isoformat()),
        "application":      app,
        "env":              _get(text, "Env"),
        "job_name":         _get(text, "Job"),
        "ds_row":           _get(text, "DSRow"),
        "source_branch":    _get(text, "Source Branch"),
        "triggered_by":     _get(text, "Triggered by"),
        "pipeline_id":      _get(text, "Pipeline Link"),
        "job_id":           _get(text, "Job Link"),
        "scenarios_passed": int(passed.group(1)) if passed else 0,
        "scenarios_failed": int(failed.group(1)) if failed else 0,
        "pass_percent":     float(pct.group(1)) if pct else 0.0,
        "duration":         dur.group(1).strip() if dur else "",
        "karate_url":       karate_url,
        "cluecumber_url":   clue_url,
        "cucumber_url":     cuke_url,
    }


# ── Save to DB ────────────────────────────────────────────────────────────────

def save_report(data):
    con = sqlite3.connect(DB_FILE)
    try:
        con.execute("""
            INSERT OR IGNORE INTO reports
            (message_id, executed_at, application, env, job_name, ds_row,
             source_branch, triggered_by, pipeline_id, job_id,
             scenarios_passed, scenarios_failed, pass_percent, duration,
             karate_url, cluecumber_url, cucumber_url)
            VALUES
            (:message_id, :executed_at, :application, :env, :job_name, :ds_row,
             :source_branch, :triggered_by, :pipeline_id, :job_id,
             :scenarios_passed, :scenarios_failed, :pass_percent, :duration,
             :karate_url, :cluecumber_url, :cucumber_url)
        """, data)
        con.commit()
        return con.execute(
            "SELECT id FROM reports WHERE message_id=?", (data["message_id"],)
        ).fetchone()[0]
    finally:
        con.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    init_db()
    print("📡 Fetching messages from Webex...")
    messages = fetch_messages()
    print(f"   Found {len(messages)} messages. Scanning for execution summaries...")

    saved = 0
    for msg in messages:
        data = parse_message(msg)
        if data:
            save_report(data)
            saved += 1
            status = "✅" if data["scenarios_failed"] == 0 else "❌"
            print(f"   {status} {data['application']:<20} | env={data['env']:<15} | "
                  f"passed={data['scenarios_passed']} failed={data['scenarios_failed']}")

    print(f"\n✅ Done! {saved} execution report(s) saved to {DB_FILE}")
    print("👉 Now run: python3 dashboard.py  →  open http://localhost:5000")


if __name__ == "__main__":
    run()
