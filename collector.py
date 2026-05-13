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
import html
from html.parser import HTMLParser
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

WEBEX_TOKEN = os.getenv("WEBEX_BOT_TOKEN")
ROOM_ID     = os.getenv("WEBEX_ROOM_ID")
DB_FILE     = "regression.db"
HEADERS     = {"Authorization": f"Bearer {WEBEX_TOKEN}"}
FAILURE_PATTERN = r"(fail|error|exception|assert|expected|mismatch|timeout)"
FAILURE_REASON_SEARCH_WINDOW = 8
MAX_FAILURE_REASON_LENGTH = 500
CONTEXT_WINDOW_BEFORE = 200
CONTEXT_WINDOW_AFTER = 400
REPORT_FETCH_TIMEOUT = 15


class _HTMLTextExtractor(HTMLParser):
    """Extract visible text and skip script/style content in HTML."""
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style"}:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style"} and self.skip_depth > 0:
            self.skip_depth -= 1

    def handle_data(self, data):
        if self.skip_depth == 0 and data:
            self.parts.append(data)

    def get_text(self):
        return "\n".join(self.parts)


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
    con.execute("CREATE INDEX IF NOT EXISTS idx_reports_executed_at ON reports(executed_at)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_reports_app_env ON reports(application, env)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_failures_report_id ON failures(report_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_failures_feature_reason ON failures(feature_file, failure_reason)")
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

def _normalize_spaces(value):
    """Normalize whitespace in a string to single spaces and trim ends."""
    return re.sub(r"\s+", " ", (value or "")).strip()


def _all_text(msg):
    """Return combined, plain-text, and markdown text payloads from a Webex message."""
    text = msg.get("text", "") or ""
    markdown = msg.get("markdown", "") or ""
    joined = "\n".join(p for p in [text, markdown] if p)
    return joined, text, markdown


def _extract_with_aliases(text, aliases):
    """Extract a value for the first matching key alias using key-value patterns."""
    for key in aliases:
        patterns = [
            rf"(?:^|[\n|])\s*(?:\*\*)?{re.escape(key)}(?:\*\*)?\s*[:=]\s*([^|\n\r]+)",
            rf"\b(?:\*\*)?{re.escape(key)}(?:\*\*)?\b\s*[:=]\s*([^|\n\r]+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if m:
                return _normalize_spaces(m.group(1))
    return ""


def _extract_links(text):
    """Extract and deduplicate HTTP(S) URLs while removing trailing punctuation."""
    links = []
    for link in re.findall(r"https?://[^\s)>\"]+", text):
        clean = link.rstrip(").,]")
        if clean not in links:
            links.append(clean)
    return links


def _pick_reason(lines, idx):
    """Pick the nearest failure-like reason line after a feature-file reference."""
    for j in range(idx, min(idx + FAILURE_REASON_SEARCH_WINDOW, len(lines))):
        line = _normalize_spaces(lines[j])
        if not line:
            continue
        if re.search(FAILURE_PATTERN, line, re.IGNORECASE):
            return line[:MAX_FAILURE_REASON_LENGTH]
    return ""


def _extract_failures_from_text(raw_text, source_url):
    """Parse HTML/text content and extract failure feature, line, and reason details."""
    if not raw_text:
        return []
    text = html.unescape(raw_text)
    if "<" in text and ">" in text:
        parser = _HTMLTextExtractor()
        parser.feed(text)
        cleaned = parser.get_text()
    else:
        cleaned = text
    lines = [_normalize_spaces(l) for l in cleaned.splitlines() if _normalize_spaces(l)]
    blob = "\n".join(lines)

    pattern = re.compile(
        r"([A-Za-z0-9_./\\-]+\.feature)(?:(?::|#L?|,\s*line\s+|\s+line\s+)(\d+))?",
        re.IGNORECASE
    )
    failures = []
    for i, line in enumerate(lines):
        for m in pattern.finditer(line):
            feature = _normalize_spaces(m.group(1))
            failure_line = m.group(2) or ""
            reason = _pick_reason(lines, i)
            if not reason:
                line_pos = blob.find(line)
                around = blob[max(0, line_pos - CONTEXT_WINDOW_BEFORE): line_pos + CONTEXT_WINDOW_AFTER]
                rm = re.search(r"(AssertionError:.*|Exception:.*|ERROR[:\s].*|FAILED[:\s].*)", around, re.IGNORECASE)
                reason = _normalize_spaces(rm.group(1)) if rm else ""
            failures.append({
                "feature_file": feature,
                "scenario_name": "",
                "failure_line": failure_line,
                "failure_reason": reason,
                "source_url": source_url
            })

    dedup = []
    seen = set()
    for f in failures:
        key = (f["feature_file"], f["failure_line"], f["failure_reason"])
        if key not in seen:
            seen.add(key)
            dedup.append(f)
    return dedup


def extract_failures_for_report(data, msg):
    """Extract failures from linked reports, falling back to Webex message content."""
    joined_text, _, _ = _all_text(msg)
    links = [u for u in [data.get("karate_url"), data.get("cluecumber_url"), data.get("cucumber_url")] if u]
    failures = []

    for url in links:
        try:
            resp = requests.get(url, timeout=REPORT_FETCH_TIMEOUT)
            if resp.ok:
                failures.extend(_extract_failures_from_text(resp.text, url))
        except Exception as exc:
            print(f"⚠️ Could not parse report URL {url}: {exc}")
            continue

    if not failures:
        failures.extend(_extract_failures_from_text(joined_text, "webex_message"))
    return failures


def parse_message(msg):
    text, plain_text, markdown_text = _all_text(msg)

    # Only process execution summary messages
    if not re.search(r"(execution\s+summary|scenarios?\s+passed|pass\s*%|scenarios?\s+failed)", text, re.IGNORECASE):
        return None

    # Extract application from key-value first, then summary header fallback.
    app = _extract_with_aliases(text, ["Application", "Application Name", "App"])
    if not app:
        header = re.search(r"Execution\s+summary(?:\s+for\s+pipeline)?\s*\|?\s*([^\n|]+)", text, re.IGNORECASE)
        if header:
            app = _normalize_spaces(header.group(1).split("|")[0])

    # Metrics line
    passed = re.search(r"(?:scenarios?\s+passed|passed)\s*[:=]\s*(\d+)", text, re.IGNORECASE)
    failed = re.search(r"(?:scenarios?\s+failed|failed)\s*[:=]\s*(\d+)", text, re.IGNORECASE)
    pct    = re.search(r"(?:pass\s*%|pass\s*rate)\s*[:=]\s*([\d.]+)", text, re.IGNORECASE)
    dur    = re.search(r"duration\s*[:=]\s*([^|\n\r]+)", text, re.IGNORECASE)

    # Report links
    links      = _extract_links(f"{plain_text}\n{markdown_text}")
    karate_url = next((l for l in links if "karate"     in l), "")
    clue_url   = next((l for l in links if "cluecumber" in l.lower()), "")
    cuke_url   = next((l for l in links if "cucumber"   in l.lower() and "karate" not in l), "")
    pipeline_link = _extract_with_aliases(text, ["Pipeline Link", "Pipeline", "Pipeline URL"])
    job_link = _extract_with_aliases(text, ["Job Link", "Job URL"])

    return {
        "message_id":       msg["id"],
        "executed_at":      msg.get("created", datetime.utcnow().isoformat()),
        "application":      app,
        "env":              _extract_with_aliases(text, ["Env", "Environment", "Environment Name"]),
        "job_name":         _extract_with_aliases(text, ["Job", "Job Name"]),
        "ds_row":           _extract_with_aliases(text, ["DSRow", "DS Row", "DS_ROW"]),
        "source_branch":    _extract_with_aliases(text, ["Source Branch", "Branch"]),
        "triggered_by":     _extract_with_aliases(text, ["Triggered by", "Triggered By", "Trigger User"]),
        "pipeline_id":      pipeline_link or next((l for l in links if "pipeline" in l.lower()), ""),
        "job_id":           job_link or next((l for l in links if "/job/" in l.lower() or "job" in l.lower()), ""),
        "scenarios_passed": int(passed.group(1)) if passed else 0,
        "scenarios_failed": int(failed.group(1)) if failed else 0,
        "pass_percent":     float(pct.group(1)) if pct else 0.0,
        "duration":         _normalize_spaces(dur.group(1)) if dur else "",
        "karate_url":       karate_url,
        "cluecumber_url":   clue_url,
        "cucumber_url":     cuke_url,
    }


# ── Save to DB ────────────────────────────────────────────────────────────────

def save_report(data, failures=None):
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
        report_id = con.execute(
            "SELECT id FROM reports WHERE message_id=?", (data["message_id"],)
        ).fetchone()[0]
        con.execute("DELETE FROM failures WHERE report_id=?", (report_id,))
        if failures:
            con.executemany("""
                INSERT INTO failures (report_id, feature_file, scenario_name, failure_line, failure_reason)
                VALUES (?, ?, ?, ?, ?)
            """, [
                (
                    report_id,
                    f.get("feature_file", ""),
                    f.get("scenario_name", ""),
                    f.get("failure_line", ""),
                    f.get("failure_reason", "")
                )
                for f in failures
            ])
        con.commit()
        return report_id
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
            failures = []
            if data["scenarios_failed"] > 0:
                failures = extract_failures_for_report(data, msg)
            save_report(data, failures)
            saved += 1
            status = "✅" if data["scenarios_failed"] == 0 else "❌"
            print(f"   {status} {data['application']:<20} | env={data['env']:<15} | "
                  f"passed={data['scenarios_passed']} failed={data['scenarios_failed']}")

    print(f"\n✅ Done! {saved} execution report(s) saved to {DB_FILE}")
    print("👉 Now run: python3 dashboard.py  →  open http://localhost:5000")


if __name__ == "__main__":
    run()
