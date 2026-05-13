"""
Minimal Flask dashboard — reads from local SQLite DB.

Usage:
    python3 dashboard.py
    Then open: http://localhost:5000
"""

import sqlite3
import argparse
from flask import Flask, render_template_string, request
from datetime import datetime, timedelta

app = Flask(__name__)
DB_FILE = "regression.db"
RECURRING_FAILURE_THRESHOLD = 3
FEATURE_NAME_MAX = 24
FAILURE_REASON_MAX = 80


def query(sql, params=()):
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows


def ensure_schema():
    con = sqlite3.connect(DB_FILE)
    try:
        report_cols = {r[1] for r in con.execute("PRAGMA table_info(reports)").fetchall()}
        if "pipeline_url" not in report_cols:
            con.execute("ALTER TABLE reports ADD COLUMN pipeline_url TEXT")
        if "job_url" not in report_cols:
            con.execute("ALTER TABLE reports ADD COLUMN job_url TEXT")
        failure_cols = {r[1] for r in con.execute("PRAGMA table_info(failures)").fetchall()}
        if "source_url" not in failure_cols:
            con.execute("ALTER TABLE failures ADD COLUMN source_url TEXT")
        con.commit()
    finally:
        con.close()


TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Regression Dashboard</title>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <style>
    :root {
      --bg: #f5f7ff;
      --card: #ffffff;
      --text: #12213f;
      --muted: #4a5d86;
      --border: #d9e1ff;
      --primary: #3f5efb;
      --accent: #fc466b;
      --pass: #0f9d58;
      --fail: #d93025;
      --warn: #c77800;
      --focus: #1a73e8;
    }
    * { box-sizing: border-box; }
    body { background:linear-gradient(135deg, #ecf0ff 0%, #fff1f4 100%); color:var(--text); font-family:'Segoe UI',sans-serif; }
    .container-fluid { width: 100%; padding: 0 20px 24px; }
    .row { display: flex; flex-wrap: wrap; margin: -6px; }
    .row.g-3 > [class*="col"] { padding: 6px; }
    .col-6, .col-md-3, .col-md-4, .col-md-8 { width: 100%; }
    @media (min-width: 768px) {
      .col-md-3 { width: 25%; }
      .col-md-4 { width: 33.3333%; }
      .col-md-8 { width: 66.6667%; }
      .col-6 { width: 50%; }
    }
    .mb-1 { margin-bottom: .25rem; }
    .mb-2 { margin-bottom: .5rem; }
    .mb-3 { margin-bottom: .75rem; }
    .mb-4 { margin-bottom: 1rem; }
    .mt-3 { margin-top: .75rem; }
    .mt-4 { margin-top: 1rem; }
    .ms-2 { margin-left: .5rem; }
    .ms-3 { margin-left: .75rem; }
    .ms-auto { margin-left: auto; }
    .small { font-size: .85rem; }
    .text-center { text-align: center; }
    .text-muted { color: var(--muted); }
    .fw-bold { font-weight: 700; }
    .fw-semibold { font-weight: 600; }
    .fs-5 { font-size: 1.2rem; }
    .d-flex { display: flex; }
    .flex-wrap { flex-wrap: wrap; }
    .gap-2 { gap: .5rem; }
    .justify-content-between { justify-content: space-between; }
    .align-items-center { align-items: center; }
    .navbar { background:linear-gradient(90deg, var(--primary), #7f7fd5); color:#fff; }
    .card { background:var(--card); border:1px solid var(--border); border-radius:14px; box-shadow:0 8px 20px rgba(34,57,132,.08); }
    .kpi  { text-align:center; padding:20px; min-height:130px; }
    .kpi .val { font-size:2rem; font-weight:700; line-height:1.1; }
    .pass { color:var(--pass); } .fail { color:var(--fail); }
    .warn { color:var(--warn); } .info { color:var(--primary); }
    .p-3 { padding: 14px; }
    .h-100 { height: 100%; }
    .table-responsive { width: 100%; overflow-x: auto; }
    .table { width: 100%; border-collapse: collapse; }
    .table td, .table th { border-top: 1px solid #e5ebff; padding: 8px; }
    .table-borderless td, .table-borderless th { border-left: 0; border-right: 0; }
    th { color:var(--muted); font-size:.75rem; text-transform:uppercase; letter-spacing:.05em; background:#f5f7ff !important; }
    tr:hover td { background:#f8faff !important; }
    a { color:#2244cc; font-weight:600; }
    .pill { border-radius:12px; padding:2px 10px; font-size:.72rem; font-weight:600; display:inline-block; }
    .pill-fail { background:#fdeceb; color:var(--fail); }
    .pill-pass { background:#e9f7ef; color:var(--pass); }
    .pill-warn { background:#fff1da; color:var(--warn); }
    .pill-info { background:#e8eeff; color:#2948c6; }
    .table td { vertical-align:top; }
    .legend-dot { width:10px; height:10px; border-radius:50%; display:inline-block; margin-right:6px; }
    .btn { border: 1px solid #ccd6ff; border-radius: 8px; background: #fff; color: #2846c8; text-decoration: none; display: inline-block; }
    .btn-sm { font-size: .78rem; padding: .18rem .45rem; }
    .btn-primary { background: var(--primary); color: #fff; border-color: var(--primary); }
    .btn-outline-secondary, .btn-outline-primary, .btn-outline-dark { background: #fff; }
    .btn-outline-dark { color: #1f305f; border-color: #bfc9f5; }
    .form-select { border: 1px solid #bccaf6; border-radius: 8px; background: #fff; padding: .18rem .4rem; min-width: 120px; }
    .form-select-sm { font-size: .82rem; }
    code { background: #f0f4ff; padding: 2px 6px; border-radius: 6px; }
    .trend-row { display: grid; grid-template-columns: 88px 1fr; gap: 8px; margin-bottom: 8px; align-items: center; }
    .trend-bars { display: flex; gap: 6px; align-items: center; }
    .trend-bar-pass { background: linear-gradient(90deg,#11a35d,#4bcb84); height: 18px; border-radius: 9px; color: #fff; font-size: .74rem; padding: 0 6px; }
    .trend-bar-fail { background: linear-gradient(90deg,#d93025,#ff7a70); height: 18px; border-radius: 9px; color: #fff; font-size: .74rem; padding: 0 6px; }
    .focus-ring:focus-visible, a:focus-visible, button:focus-visible, select:focus-visible {
      outline: 3px solid var(--focus);
      outline-offset: 2px;
    }
  </style>
</head>
<body>

<nav class="navbar" style="padding:12px 20px">
  <span class="fw-bold fs-5">🧪 Regression Quality Board</span>
  <span class="small ms-auto" style="opacity:.92">{{ total }} total runs in database</span>
</nav>

<!-- Filters -->
<div style="background:#fff;border-bottom:1px solid var(--border);padding:12px 20px">
  <form method="get" class="d-flex gap-2 flex-wrap align-items-center">
    <label class="small fw-semibold" for="days">Time Window</label>
    <select id="days" name="days" class="form-select form-select-sm focus-ring" style="width:auto">
      {% for d in [1,3,7,14,30] %}
      <option value="{{d}}" {{'selected' if filters.days==d}}>Last {{d}} day{{'s' if d>1}}</option>
      {% endfor %}
    </select>
    <label class="small fw-semibold" for="app">Application</label>
    <select id="app" name="app" class="form-select form-select-sm focus-ring" style="width:auto">
      <option value="">All Apps</option>
      {% for a in apps %}<option {{'selected' if filters.app==a}}>{{a}}</option>{% endfor %}
    </select>
    <label class="small fw-semibold" for="env">Environment</label>
    <select id="env" name="env" class="form-select form-select-sm focus-ring" style="width:auto">
      <option value="">All Envs</option>
      {% for e in envs %}<option {{'selected' if filters.env==e}}>{{e}}</option>{% endfor %}
    </select>
    <button class="btn btn-sm btn-primary focus-ring">Apply</button>
    <a href="/" class="btn btn-sm btn-outline-secondary focus-ring">Reset</a>
  </form>
</div>

<div class="container-fluid mt-4">

  <!-- KPI Row -->
  <div class="row g-3 mb-4">
    <div class="col-6 col-md-3">
      <div class="card kpi">
        <div class="text-muted small">Total Runs</div>
        <div class="val info">{{kpi.runs}}</div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card kpi">
        <div class="text-muted small">Passed Scenarios</div>
        <div class="val pass">{{kpi.passed}}</div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card kpi">
        <div class="text-muted small">Failed Scenarios</div>
        <div class="val fail">{{kpi.failed}}</div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card kpi">
        <div class="text-muted small">Avg Pass Rate</div>
        <div class="val {{'pass' if kpi.avg_pct>=95 else 'warn' if kpi.avg_pct>=80 else 'fail'}}">
          {{kpi.avg_pct}}%
        </div>
      </div>
    </div>
  </div>

  <div class="row g-3 mb-4">
    <!-- Trend Chart -->
    <div class="col-md-8">
      <div class="card p-3">
        <div class="text-muted small mb-2">📈 Daily pass/fail trend</div>
        <div class="small mb-2">
          <span class="legend-dot" style="background:#2ca45a"></span> Passed
          <span class="legend-dot ms-3" style="background:#e53935"></span> Failed
        </div>
        {% for d in chart_data %}
        <div class="trend-row">
          <div class="small text-muted">{{d.date}}</div>
          <div class="trend-bars">
            <div class="trend-bar-pass" aria-label="Passed: {{d.passed}} scenarios" style="width: {{ (d.passed / chart_scale * 100) if chart_scale else 0 }}%;">{{d.passed}}</div>
            <div class="trend-bar-fail" aria-label="Failed: {{d.failed}} scenarios" style="width: {{ (d.failed / chart_scale * 100) if chart_scale else 0 }}%;">{{d.failed}}</div>
          </div>
        </div>
        {% else %}
        <div class="small text-muted">No trend data in this range.</div>
        {% endfor %}
      </div>
    </div>
    <!-- Failure Summary -->
    <div class="col-md-4">
      <div class="card p-3 h-100">
        <div class="text-muted small mb-2">💥 Failure analysis</div>
        <div class="d-flex justify-content-between align-items-center mb-2">
          <span class="small">Executions with failures</span>
          <span class="pill pill-fail">{{failure_summary.failed_executions}}</span>
        </div>
        <div class="d-flex justify-content-between align-items-center mb-2">
          <span class="small">Unique failing features</span>
          <span class="pill pill-warn">{{failure_summary.unique_features}}</span>
        </div>
        <div class="d-flex justify-content-between align-items-center mb-3">
          <span class="small">Unique failure reasons</span>
          <span class="pill pill-info">{{failure_summary.unique_reasons}}</span>
        </div>
        <div class="text-muted small mb-1">Top reasons</div>
        {% for r in top_reasons %}
        <div class="small d-flex justify-content-between mb-1">
          <span title="{{r['failure_reason']}}">{{r['failure_reason'][:50]}}{{'…' if r['failure_reason'] and r['failure_reason']|length>50 else ''}}</span>
          <span class="pill pill-fail">{{r['cnt']}}</span>
        </div>
        {% else %}
        <div class="text-muted small">No failure reasons captured in this range.</div>
        {% endfor %}
      </div>
    </div>
  </div>

  <!-- Execution history -->
  <div class="card p-3 mb-4">
    <div class="text-muted small mb-3">📋 Execution history</div>
    <div class="table-responsive">
      <table class="table table-sm table-hover table-borderless align-middle" aria-label="Execution history">
        <thead><tr>
          <th scope="col">Execution Date</th>
          <th scope="col">Application</th>
          <th scope="col">Environment</th>
          <th scope="col">DS Row</th>
          <th scope="col">Job Name</th>
          <th scope="col">Branch</th>
          <th scope="col">Triggered By</th>
          <th scope="col">Passed</th>
          <th scope="col">Failed</th>
          <th scope="col">Pass%</th>
          <th scope="col">Duration</th>
          <th scope="col">Links</th>
        </tr></thead>
        <tbody>
        {% for r in reports %}
        <tr>
          <td class="small">{{r['executed_at'][:16].replace('T',' ')}}</td>
          <td><strong>{{r['application'] or '—'}}</strong></td>
          <td><span class="pill pill-info">{{r['env'] or '—'}}</span></td>
          <td class="text-center">{{r['ds_row'] or '—'}}</td>
          <td class="small" title="{{r['job_name']}}">{{r['job_name'][:30]}}{{'…' if r['job_name'] and r['job_name']|length>30 else ''}}</td>
          <td class="small">{{r['source_branch'] or '—'}}</td>
          <td class="small">{{r['triggered_by'] or '—'}}</td>
          <td class="pass">{{r['scenarios_passed']}}</td>
          <td class="{{'fail' if r['scenarios_failed']>0 else 'pass'}}"><strong>{{r['scenarios_failed']}}</strong></td>
          <td>{{r['pass_percent']}}%</td>
          <td class="small">{{r['duration'] or '—'}}</td>
          <td class="small">
            {% if r['karate_url_safe'] %}<a class="btn btn-sm btn-outline-primary focus-ring py-0 px-2 mb-1" href="{{r['karate_url_safe']}}" target="_blank" rel="noopener noreferrer">Karate</a>{% endif %}
            {% if r['cluecumber_url_safe'] %}<a class="btn btn-sm btn-outline-primary focus-ring py-0 px-2 mb-1" href="{{r['cluecumber_url_safe']}}" target="_blank" rel="noopener noreferrer">Cluecumber</a>{% endif %}
            {% if r['cucumber_url_safe'] %}<a class="btn btn-sm btn-outline-primary focus-ring py-0 px-2 mb-1" href="{{r['cucumber_url_safe']}}" target="_blank" rel="noopener noreferrer">Cucumber</a>{% endif %}
            {% if r['pipeline_url_safe'] %}<a class="btn btn-sm btn-outline-dark focus-ring py-0 px-2 mb-1" href="{{r['pipeline_url_safe']}}" target="_blank" rel="noopener noreferrer">Pipeline</a>{% endif %}
            {% if r['job_url_safe'] %}<a class="btn btn-sm btn-outline-dark focus-ring py-0 px-2 mb-1" href="{{r['job_url_safe']}}" target="_blank" rel="noopener noreferrer">Job</a>{% endif %}
          </td>
        </tr>
        {% else %}
        <tr><td colspan="12" class="text-center text-muted py-4">No data found. Run <code>python3 collector.py</code> first.</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Failure details -->
  <div class="card p-3 mb-4">
    <div class="text-muted small mb-3">💥 Failure details</div>
    <div class="table-responsive">
      <table class="table table-sm table-hover table-borderless align-middle" aria-label="Execution and failure details">
        <thead><tr>
          <th scope="col">Execution Date</th>
          <th scope="col">Application</th>
          <th scope="col">Environment</th>
          <th scope="col">DS Row</th>
          <th scope="col">Job Name</th>
          <th scope="col">Passed</th>
          <th scope="col">Failed</th>
          <th scope="col">Failure Feature File</th>
          <th scope="col">Failure Line</th>
          <th scope="col">Failure Reason</th>
          <th scope="col">Scenario Name</th>
          <th scope="col">Source</th>
        </tr></thead>
        <tbody>
        {% for r in failure_rows %}
        <tr>
          <td class="small">{{r['executed_at'][:16].replace('T',' ')}}</td>
          <td><strong>{{r['application']}}</strong></td>
          <td><span class="pill pill-info">{{r['env']}}</span></td>
          <td class="text-center">{{r['ds_row']}}</td>
          <td class="small text-muted" title="{{r['job_name']}}">
            {{r['job_name'][:25]}}{{'…' if r['job_name'] and r['job_name']|length>25 else ''}}
          </td>
          <td class="pass">{{r['scenarios_passed']}}</td>
          <td class="{{'fail' if r['scenarios_failed']>0 else 'pass'}}">
            <strong>{{r['scenarios_failed']}}</strong>
          </td>
          <td class="small">{{r['feature_file'] if r['feature_file'] else '—'}}</td>
          <td class="small text-center">{{r['failure_line'] if r['failure_line'] else '—'}}</td>
          <td class="small" title="{{r['failure_reason']}}">
            {{r['failure_reason'][:failure_reason_max] if r['failure_reason'] else '—'}}{{'…' if r['failure_reason'] and r['failure_reason']|length>failure_reason_max else ''}}
          </td>
          <td class="small" title="{{r['scenario_name']}}">{{r['scenario_name'] if r['scenario_name'] else '—'}}</td>
          <td>
            {% if r['source_url_safe'] %}
              <a class="focus-ring" href="{{r['source_url_safe']}}" target="_blank" rel="noopener noreferrer">Report</a>
            {% else %}
              <span class="pill pill-warn">Webex Msg</span>
            {% endif %}
          </td>
        </tr>
        {% else %}
        <tr>
          <td colspan="12" class="text-center text-muted py-4">No failure data captured in this range.</td>
        </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Recurring failures -->
  <div class="card p-3 mb-4">
    <div class="text-muted small mb-3">🔁 Recurring failures (last 7 days)</div>
    <div class="table-responsive">
      <table class="table table-sm table-hover table-borderless align-middle" aria-label="Recurring failures">
        <thead><tr>
          <th scope="col">Feature File</th>
          <th scope="col">Failure Reason</th>
          <th scope="col">Weekly Count</th>
          <th scope="col">Affected Executions</th>
          <th scope="col">First Seen</th>
          <th scope="col">Last Seen</th>
        </tr></thead>
        <tbody>
        {% for r in recurring %}
        <tr>
          <td class="small">{{r['feature_file']}}</td>
          <td class="small" title="{{r['failure_reason']}}">{{r['failure_reason'][:80]}}{{'…' if r['failure_reason'] and r['failure_reason']|length>80 else ''}}</td>
          <td><span class="pill {{'pill-fail' if r['weekly_count'] >= recurring_threshold else 'pill-warn'}}">{{r['weekly_count']}}</span></td>
          <td>{{r['affected_executions']}}</td>
          <td class="small">{{r['first_seen'][:16].replace('T',' ') if r['first_seen'] else '—'}}</td>
          <td class="small">{{r['last_seen'][:16].replace('T',' ') if r['last_seen'] else '—'}}</td>
        </tr>
        {% else %}
        <tr><td colspan="6" class="text-center text-muted py-4">No recurring failures in the last 7 days.</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>

</body>
</html>
"""


@app.route("/")
def index():
    ensure_schema()
    days   = int(request.args.get("days", 7))
    app_f  = request.args.get("app", "")
    env_f  = request.args.get("env", "")
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    where  = ["r.executed_at >= ?"]
    params = [cutoff]
    if app_f: where.append("r.application = ?"); params.append(app_f)
    if env_f: where.append("r.env = ?");         params.append(env_f)
    sql_where = " AND ".join(where)

    reports    = query(f"SELECT * FROM reports r WHERE {sql_where} ORDER BY r.executed_at DESC", params)
    total      = query("SELECT COUNT(*) as c FROM reports")[0]["c"]
    apps       = [r["application"] for r in query("SELECT DISTINCT application FROM reports WHERE application != ''")]
    envs       = [r["env"]         for r in query("SELECT DISTINCT env FROM reports WHERE env != ''")]

    kpi_rows   = query(f"SELECT * FROM reports r WHERE {sql_where}", params)
    runs       = len(kpi_rows)
    passed     = sum(r["scenarios_passed"] for r in kpi_rows)
    failed     = sum(r["scenarios_failed"] for r in kpi_rows)
    avg_pct    = round(sum(r["pass_percent"] for r in kpi_rows) / runs, 1) if runs else 0

    recurring = query("""
        SELECT
            f.feature_file,
            f.failure_reason,
            COUNT(*) as weekly_count,
            COUNT(DISTINCT r.id) as affected_executions,
            MIN(r.executed_at) as first_seen,
            MAX(r.executed_at) as last_seen
        FROM reports r
        JOIN failures f ON f.report_id = r.id
        WHERE r.executed_at >= ?
          AND f.feature_file != ''
          AND f.failure_reason != ''
        GROUP BY f.feature_file, f.failure_reason
        ORDER BY weekly_count DESC, last_seen DESC
        LIMIT 20
    """, [(datetime.utcnow() - timedelta(days=7)).isoformat()])

    top_reasons = query(f"""
        SELECT f.failure_reason, COUNT(*) as cnt
        FROM failures f
        JOIN reports r ON r.id = f.report_id
        WHERE {sql_where} AND f.failure_reason != ''
        GROUP BY f.failure_reason
        ORDER BY cnt DESC
        LIMIT 5
    """, params)

    chart_rows = query(f"""
        SELECT date(executed_at) as date,
               SUM(scenarios_passed) as passed,
               SUM(scenarios_failed) as failed
        FROM reports r WHERE {sql_where}
        GROUP BY date(executed_at) ORDER BY date
    """, params)
    chart_data = [{"date": r["date"], "passed": r["passed"], "failed": r["failed"]}
                  for r in chart_rows]
    chart_scale = max((max(d.get("passed") or 0, d.get("failed") or 0) for d in chart_data), default=1)

    failure_rows = query(f"""
        SELECT
            r.executed_at,
            r.application,
            r.env,
            r.ds_row,
            r.job_name,
            r.scenarios_passed,
            r.scenarios_failed,
            f.feature_file,
            f.scenario_name,
            f.failure_line,
            f.failure_reason,
            f.source_url
        FROM reports r
        JOIN failures f ON f.report_id = r.id
        WHERE {sql_where}
        ORDER BY r.executed_at DESC, f.feature_file
    """, params)

    failure_summary = query(f"""
        SELECT
            COUNT(DISTINCT CASE WHEN r.scenarios_failed > 0 THEN r.id END) as failed_executions,
            COUNT(DISTINCT CASE WHEN f.feature_file != '' THEN f.feature_file END) as unique_features,
            COUNT(DISTINCT CASE WHEN f.failure_reason != '' THEN f.failure_reason END) as unique_reasons
        FROM reports r
        LEFT JOIN failures f ON f.report_id = r.id
        WHERE {sql_where}
    """, params)[0]

    processed_failure_rows = []
    for row in failure_rows:
        r = dict(row)
        value = r.get("source_url") or ""
        r["source_url_safe"] = value if isinstance(value, str) and value.startswith(("http://", "https://")) else ""
        processed_failure_rows.append(r)

    processed_reports = []
    for row in reports:
        r = dict(row)
        for key in ["karate_url", "cluecumber_url", "cucumber_url", "pipeline_url", "job_url"]:
            value = r.get(key) or ""
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                r[f"{key}_safe"] = value
            else:
                r[f"{key}_safe"] = ""
        processed_reports.append(r)

    return render_template_string(
        TEMPLATE,
        reports=processed_reports,
        failure_rows=processed_failure_rows,
        total=total,
        apps=apps,
        envs=envs,
        kpi=dict(runs=runs, passed=passed, failed=failed, avg_pct=avg_pct),
        recurring=recurring,
        top_reasons=top_reasons,
        failure_summary=failure_summary,
        chart_data=chart_data,
        chart_scale=chart_scale,
        recurring_threshold=RECURRING_FAILURE_THRESHOLD,
        feature_name_max=FEATURE_NAME_MAX,
        failure_reason_max=FAILURE_REASON_MAX,
        filters=dict(days=days, app=app_f, env=env_f),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run regression dashboard")
    parser.add_argument("--port", type=int, default=5000, help="Port to run dashboard on (default: 5000)")
    args = parser.parse_args()
    print(f"🚀 Dashboard running → http://localhost:{args.port}")
    app.run(debug=False, port=args.port)
