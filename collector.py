"""
Run this script to pull messages from your Webex group chat
and save execution summaries into a local SQLite database.

Usage:
    python3 collector.py                # interactive menu to choose date range
    python3 collector.py --days 7       # last 7 days (non-interactive)
    python3 collector.py --range today  # today only (non-interactive)
    python3 collector.py --range week   # this week (non-interactive)
    python3 collector.py --range 30days # last 30 days (non-interactive)

Supported --range values: today, 7days, 30days, week
"""

import argparse
import re
import sqlite3
import requests
import os
import html
from html.parser import HTMLParser
from datetime import datetime, timedelta, timezone
from typing import List, Optional
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
JSON_SIDECAR_FETCH_TIMEOUT = 10
INLINE_FAILURE_PATTERN = re.compile(
    r"([A-Za-z0-9_./\\-]+\.feature)(?::(\d+))?\s*-\s*(.+)",
    re.IGNORECASE
)
JSON_SIDECAR_CANDIDATE_FILES = [
    "karate-summary-json.txt",
    "karate-summary.json",
    "summary.json",
    "data.json",
    "report.json",
]
JSON_FEATURE_KEYS = {"feature", "feature_file", "uri", "path", "location", "featureName", "relativePath", "fileName"}
JSON_SCENARIO_KEYS = {"scenario", "scenario_name", "scenarioName", "name"}
JSON_LINE_KEYS = {"line", "lineNumber", "failedLine", "errorLine"}
JSON_REASON_KEYS = {"errorMessage", "failureReason", "reason", "message", "error", "stepErrorMessage", "stackTrace"}


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


# ── Date-range helpers ────────────────────────────────────────────────────────

# Maps canonical range names → (label, after_dt_factory)
_RANGE_CHOICES = {
    "today":   "Current date (today only)",
    "7days":   "Last 7 days",
    "30days":  "Last 30 days",
    "week":    "This week (Mon – today)",
}


def _after_dt_for_range(range_key: str) -> datetime:
    """Return the UTC datetime representing the start of the requested range."""
    now = datetime.now(timezone.utc)
    if range_key == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "7days":
        return (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "30days":
        return (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "week":
        # Monday of the current week
        monday = now - timedelta(days=now.weekday())
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"Unknown range key: {range_key!r}")


def choose_date_range() -> tuple:
    """Show an interactive menu and return (range_key, after_dt)."""
    menu_items = [
        ("today",  "1) Current date (today only)"),
        ("7days",  "2) Last 7 days"),
        ("30days", "3) Last 30 days"),
        ("week",   "4) This week (Mon – today)"),
    ]
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  📅  Choose data range to collect")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    for _, label in menu_items:
        print(f"     {label}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    valid = {"1": "today", "2": "7days", "3": "30days", "4": "week"}
    while True:
        try:
            choice = input("Enter choice (1-4) [default: 2]: ").strip() or "2"
        except (EOFError, KeyboardInterrupt):
            print("\nUsing default: last 7 days")
            choice = "2"
        if choice in valid:
            range_key = valid[choice]
            after_dt = _after_dt_for_range(range_key)
            print(f"\n✅ Range selected: {_RANGE_CHOICES[range_key]}")
            print(f"   Fetching messages from {after_dt.strftime('%Y-%m-%d')} UTC onwards\n")
            return range_key, after_dt
        print("   ⚠️  Please enter a number between 1 and 4.")


# ── Webex polling ─────────────────────────────────────────────────────────────

def fetch_messages(after_dt: Optional[datetime] = None, page_size: int = 200) -> List[dict]:
    """Fetch Webex room messages, optionally limited to those created on/after *after_dt*.

    The Webex messages endpoint returns results in reverse chronological order
    (newest first) and does not support an ``after`` query parameter directly.
    We therefore page through results in batches of *page_size* and stop as
    soon as a message's ``created`` timestamp is older than *after_dt*.

    If *after_dt* is None all available messages (up to Webex's hard limit) are
    returned in a single request of size *page_size*.
    """
    url = "https://webexapis.com/v1/messages"
    # Webex hard-cap per request is 1 000; stay well within it.
    page_size = min(max(1, page_size), 1000)

    all_messages: List[dict] = []
    before_message_id: Optional[str] = None  # cursor for pagination

    while True:
        params: dict = {"roomId": ROOM_ID, "max": page_size}
        if before_message_id:
            params["beforeMessage"] = before_message_id

        r = requests.get(url, headers=HEADERS, params=params)
        r.raise_for_status()
        page = r.json().get("items", [])

        if not page:
            break

        if after_dt is None:
            all_messages.extend(page)
            break  # single-page, no date filtering

        reached_cutoff = False
        for msg in page:
            created_raw = msg.get("created", "")
            try:
                # Webex returns ISO 8601 with trailing Z
                created_dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                created_dt = None

            if created_dt is not None and created_dt < after_dt:
                reached_cutoff = True
                break
            all_messages.append(msg)

        if reached_cutoff or len(page) < page_size:
            break  # no more pages within the requested range

        before_message_id = page[-1]["id"]  # advance cursor

    return all_messages


# ── Message parser ────────────────────────────────────────────────────────────

def _normalize_spaces(value):
    """Normalize whitespace in a string to single spaces and trim ends."""
    return re.sub(r"\s+", " ", (value or "")).strip()


def _all_text(msg):
    """Return combined text payloads from a Webex message (text/markdown/html)."""
    text = msg.get("text", "") or ""
    markdown = msg.get("markdown", "") or ""
    html_payload = msg.get("html", "") or ""
    joined = "\n".join(p for p in [text, markdown, html_payload] if p)
    return joined, text, markdown, html_payload


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
        clean = re.sub(r"[)\],.]+$", "", link)
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
    lines = []
    for raw_line in cleaned.splitlines():
        normalized = _normalize_spaces(raw_line)
        if normalized:
            lines.append(normalized.replace("—", "-").replace("–", "-"))
    blob = "\n".join(lines)

    # Supports formats like file.feature:123, file.feature#L45, file.feature, line 10.
    pattern = re.compile(
        r"([A-Za-z0-9_./\\-]+\.feature)(?:(?::|#L?|,\s*line\s+|\s+line\s+)(\d+))?",
        re.IGNORECASE
    )
    failures = []
    for i, line in enumerate(lines):
        inline = INLINE_FAILURE_PATTERN.search(line)
        if inline:
            failures.append({
                "feature_file": _normalize_spaces(inline.group(1)),
                "scenario_name": "",
                "failure_line": inline.group(2) or "",
                "failure_reason": _normalize_spaces(inline.group(3))[:MAX_FAILURE_REASON_LENGTH],
                "source_url": source_url
            })
            continue
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


def _json_sidecar_urls(url):
    """Build likely JSON sidecar URLs for Karate/Cluecumber reports."""
    base = url.rsplit("/", 1)[0] + "/"
    candidates = [base + name for name in JSON_SIDECAR_CANDIDATE_FILES]
    if url.lower().endswith(".html"):
        candidates.append(re.sub(r"\.(?:html|htm)$", ".json", url, flags=re.IGNORECASE))
    return list(dict.fromkeys(candidates))


def _extract_failures_from_json_payload(payload, source_url):
    """Extract failure-like records from JSON payloads with flexible schema."""
    failures = []
    seen = set()

    def _str(v):
        return _normalize_spaces(str(v)) if v is not None else ""

    def _walk(node):
        if isinstance(node, dict):
            feature = ""
            scenario = ""
            failure_line = ""
            reason = ""
            status = _str(node.get("status")).lower() if "status" in node else ""

            for k, v in node.items():
                if k in JSON_FEATURE_KEYS and not feature:
                    value = _str(v)
                    m = re.search(r"([A-Za-z0-9_./\\-]+\.feature)", value, re.IGNORECASE)
                    feature = m.group(1) if m else value
                if k in JSON_SCENARIO_KEYS and not scenario:
                    scenario = _str(v)
                if k in JSON_LINE_KEYS and not failure_line:
                    failure_line = re.sub(r"\D+", "", _str(v))
                if k in JSON_REASON_KEYS and not reason:
                    reason = _str(v)[:MAX_FAILURE_REASON_LENGTH]

            if status in {"failed", "fail", "error"} and not reason:
                reason = "Test failed (no error details available in report)"

            if feature and (reason or status in {"failed", "fail", "error"}):
                key = (feature, failure_line, reason)
                if key not in seen:
                    seen.add(key)
                    failures.append({
                        "feature_file": feature,
                        "scenario_name": scenario,
                        "failure_line": failure_line,
                        "failure_reason": reason,
                        "source_url": source_url
                    })

            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    return failures


def extract_failures_for_report(data, msg):
    """Extract failures from linked reports, falling back to Webex message content."""
    joined_text, _, _, _ = _all_text(msg)
    links = [u for u in [data.get("karate_url"), data.get("cluecumber_url"), data.get("cucumber_url")] if u]
    failures = []
    total_http_requests = 0
    extracted_from_report_text = 0
    extracted_from_json = 0
    json_fetch_failures = 0

    for url in links:
        try:
            resp = requests.get(url, timeout=REPORT_FETCH_TIMEOUT)
            total_http_requests += 1
            if resp.ok:
                text_failures = _extract_failures_from_text(resp.text, url)
                failures.extend(text_failures)
                extracted_from_report_text += len(text_failures)
                if not text_failures:
                    for json_url in _json_sidecar_urls(url):
                        try:
                            jr = requests.get(json_url, timeout=JSON_SIDECAR_FETCH_TIMEOUT)
                            total_http_requests += 1
                            if jr.ok:
                                payload = jr.json()
                                json_failures = _extract_failures_from_json_payload(payload, json_url)
                                if json_failures:
                                    failures.extend(json_failures)
                                    extracted_from_json += len(json_failures)
                                    break
                        except Exception:
                            json_fetch_failures += 1
                            continue
        except Exception as exc:
            print(f"⚠️ Could not parse report URL {url}: {exc}")
            continue

    if not failures:
        text_failures = _extract_failures_from_text(joined_text, "webex_message")
        failures.extend(text_failures)
        print(
            f"   ℹ️ failure extraction stats: total_http_requests={total_http_requests}, "
            f"text={extracted_from_report_text}, json={extracted_from_json}, json_fetch_failures={json_fetch_failures}, "
            f"webex_text={len(text_failures)}"
        )
    else:
        print(
            f"   ℹ️ failure extraction stats: total_http_requests={total_http_requests}, "
            f"text={extracted_from_report_text}, json={extracted_from_json}, json_fetch_failures={json_fetch_failures}, webex_text=0"
        )
    return failures


def parse_message(msg):
    text, plain_text, markdown_text, html_payload = _all_text(msg)

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
    links      = _extract_links(f"{plain_text}\n{markdown_text}\n{html_payload}")
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
        "job_id":           job_link or next((l for l in links if re.search(r"/jobs?/|[?&]job(?:id)?=", l, re.IGNORECASE)), ""),
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

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Collect Webex regression messages into the local SQLite DB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 collector.py                 # interactive menu
  python3 collector.py --days 7        # last 7 days
  python3 collector.py --range today   # today only
  python3 collector.py --range week    # this week (Mon – today)
  python3 collector.py --range 30days  # last 30 days
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--days",
        type=int,
        metavar="N",
        help="Fetch messages from the last N days (e.g. --days 7).",
    )
    group.add_argument(
        "--range",
        choices=list(_RANGE_CHOICES.keys()),
        metavar="RANGE",
        help="Named range: today | 7days | 30days | week.",
    )
    return parser.parse_args()


def _known_message_ids() -> set:
    """Return the set of message IDs already stored in the database."""
    try:
        con = sqlite3.connect(DB_FILE)
        rows = con.execute("SELECT message_id FROM reports").fetchall()
        con.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


def run():
    args = _parse_args()

    # Determine after_dt from CLI flags or interactive menu
    if args.days is not None:
        after_dt = (datetime.now(timezone.utc) - timedelta(days=args.days)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        label = f"last {args.days} day(s)"
    elif args.range is not None:
        after_dt = _after_dt_for_range(args.range)
        label = _RANGE_CHOICES[args.range]
    else:
        _, after_dt = choose_date_range()
        label = f"since {after_dt.strftime('%Y-%m-%d')}"

    init_db()

    print(f"📡 Fetching Webex messages ({label})…")
    messages = fetch_messages(after_dt=after_dt)
    print(f"   Found {len(messages)} message(s) in the selected window.")

    # Skip messages already stored (deduplication by message_id)
    known_ids = _known_message_ids()
    new_messages = [m for m in messages if m.get("id") not in known_ids]
    skipped = len(messages) - len(new_messages)
    if skipped:
        print(f"   ⏭️  Skipping {skipped} already-stored message(s).")
    print(f"   Scanning {len(new_messages)} new message(s) for execution summaries…")

    saved = 0
    parsed = 0
    for msg in new_messages:
        data = parse_message(msg)
        if data:
            parsed += 1
            failures = []
            if data["scenarios_failed"] > 0:
                failures = extract_failures_for_report(data, msg)
            save_report(data, failures)
            saved += 1
            status = "✅" if data["scenarios_failed"] == 0 else "❌"
            print(f"   {status} {data['application']:<20} | env={data['env']:<15} | "
                  f"passed={data['scenarios_passed']} failed={data['scenarios_failed']}")

    print(f"\n✅ Done! parsed={parsed}, saved={saved} execution report(s) to {DB_FILE}")
    print("👉 Now run: python3 dashboard.py  →  open http://localhost:5000")


if __name__ == "__main__":
    run()
