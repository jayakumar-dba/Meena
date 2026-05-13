"""
Minimal Flask dashboard — reads from local SQLite DB.

Usage:
    python3 dashboard.py
    Then open: http://localhost:5000
"""

import sqlite3
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


TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Regression Dashboard</title>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"/>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
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
    body { background:linear-gradient(135deg, #ecf0ff 0%, #fff1f4 100%); color:var(--text); font-family:'Segoe UI',sans-serif; }
    .navbar { background:linear-gradient(90deg, var(--primary), #7f7fd5); color:#fff; }
    .card { background:var(--card); border:1px solid var(--border); border-radius:14px; box-shadow:0 8px 20px rgba(34,57,132,.08); }
    .kpi  { text-align:center; padding:20px; min-height:130px; }
    .kpi .val { font-size:2rem; font-weight:700; line-height:1.1; }
    .pass { color:var(--pass); } .fail { color:var(--fail); }
    .warn { color:var(--warn); } .info { color:var(--primary); }
    th { color:var(--muted); font-size:.75rem; text-transform:uppercase; letter-spacing:.05em; background:#f5f7ff !important; }
    tr:hover { background:#f8faff !important; }
    a { color:#2244cc; font-weight:600; }
    .pill { border-radius:12px; padding:2px 10px; font-size:.72rem; font-weight:600; display:inline-block; }
    .pill-fail { background:#fdeceb; color:var(--fail); }
    .pill-pass { background:#e9f7ef; color:var(--pass); }
    .pill-warn { background:#fff1da; color:var(--warn); }
    .pill-info { background:#e8eeff; color:#2948c6; }
    .table td { vertical-align:top; }
    .legend-dot { width:10px; height:10px; border-radius:50%; display:inline-block; margin-right:6px; }
    .focus-ring:focus-visible, a:focus-visible, button:focus-visible, select:focus-visible {
      outline: 3px solid var(--focus);
      outline-offset: 2px;
    }
  </style>
</head>
<body>

<nav class="navbar" style="padding:12px 20px">
  <span class="fw-bold fs-5" aria-label="Dashboard title">🧪 Regression Quality Board</span>
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
        <canvas id="chart" height="100"></canvas>
      </div>
    </div>
    <!-- Top Failures -->
    <div class="col-md-4">
      <div class="card p-3 h-100">
        <div class="text-muted small mb-2">🔥 Weekly recurring failures</div>
        {% for r in recurring %}
        <div class="d-flex justify-content-between align-items-center mb-2">
          <span class="small" title="{{r['failure_reason']}}">
            {{r['feature_file'][:feature_name_max]}}{{'…' if r['feature_file'] and r['feature_file']|length>feature_name_max else ''}}
          </span>
          <span class="small text-muted ms-2">wk {{r['week_key']}}</span>
          <span class="pill pill-fail">{{r['weekly_count']}}x in week</span>
        </div>
        {% else %}
        <div class="text-muted small text-center mt-3">🎉 No recurring failures in this range.</div>
        {% endfor %}
      </div>
    </div>
  </div>

  <!-- Execution and failure table -->
  <div class="card p-3 mb-4">
    <div class="text-muted small mb-3">📋 Execution + failure details</div>
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
          <th scope="col">Report Links</th>
          <th scope="col">Weekly Recurrence</th>
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
          <td class="small">
            {% if r['karate_url'] %}
              <a class="focus-ring" href="{{r['karate_url']}}" target="_blank" rel="noopener noreferrer">Karate</a>
            {% endif %}
            {% if r['cluecumber_url'] %}
              <a class="focus-ring" href="{{r['cluecumber_url']}}" target="_blank" rel="noopener noreferrer">Cluecumber</a>
            {% endif %}
            {% if r['cucumber_url'] %}
              <a class="focus-ring" href="{{r['cucumber_url']}}" target="_blank" rel="noopener noreferrer">Cucumber</a>
            {% endif %}
            {% if r['pipeline_id'] and 'http' in r['pipeline_id'] %}
              <a class="focus-ring" href="{{r['pipeline_id']}}" target="_blank" rel="noopener noreferrer">Pipeline</a>
            {% endif %}
            {% if r['job_id'] and 'http' in r['job_id'] %}
              <a class="focus-ring" href="{{r['job_id']}}" target="_blank" rel="noopener noreferrer">Job</a>
            {% endif %}
          </td>
          <td>
            {% if r['weekly_recurrence'] and r['weekly_recurrence'] > 0 %}
              <span class="pill {{'pill-fail' if r['weekly_recurrence'] >= recurring_threshold else 'pill-warn'}}">{{r['weekly_recurrence']}}x</span>
            {% else %}
              <span class="pill pill-pass">0</span>
            {% endif %}
          </td>
        </tr>
        {% else %}
        <tr>
          <td colspan="12" class="text-center text-muted py-4">
            No data found. Run <code>python3 collector.py</code> first.
          </td>
        </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>

<script>
const data = {{ chart_data | tojson }};
new Chart(document.getElementById('chart'), {
  type: 'bar',
  data: {
    labels: data.map(d => d.date),
    datasets: [
      { label: 'Passed', data: data.map(d => d.passed), backgroundColor: '#2ca45a' },
      { label: 'Failed', data: data.map(d => d.failed), backgroundColor: '#e53935' }
    ]
  },
  options: {
    responsive: true,
    plugins: { legend: { labels: { color: '#23314d' } } },
    scales: {
      x: { ticks: { color: '#4a5d86' }, grid: { color: '#e2e8ff' } },
      y: { ticks: { color: '#4a5d86' }, grid: { color: '#e2e8ff' } }
    }
  }
});
</script>
</body>
</html>
"""


@app.route("/")
def index():
    days   = int(request.args.get("days", 7))
    app_f  = request.args.get("app", "")
    env_f  = request.args.get("env", "")
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    where  = ["r.executed_at >= ?"]
    params = [cutoff]
    if app_f: where.append("application = ?"); params.append(app_f)
    if env_f: where.append("env = ?");         params.append(env_f)
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

    recurring = query(f"""
        SELECT strftime('%Y-%W', r.executed_at) as week_key, f.feature_file, f.failure_reason, COUNT(*) as weekly_count
        FROM reports r
        JOIN failures f ON f.report_id = r.id
        WHERE {sql_where}
          AND f.feature_file != ''
          AND f.failure_reason != ''
        GROUP BY week_key, f.feature_file, f.failure_reason
        ORDER BY weekly_count DESC
        LIMIT 6
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

    failure_rows = query(f"""
        SELECT
            r.executed_at,
            r.application,
            r.env,
            r.ds_row,
            r.job_name,
            r.scenarios_passed,
            r.scenarios_failed,
            r.karate_url,
            r.cluecumber_url,
            r.cucumber_url,
            r.pipeline_id,
            r.job_id,
            f.feature_file,
            f.failure_line,
            f.failure_reason,
            CASE
                WHEN IFNULL(f.feature_file, '') != '' AND IFNULL(f.failure_reason, '') != '' THEN (
                    SELECT COUNT(*)
                    FROM failures f2
                    JOIN reports r2 ON r2.id = f2.report_id
                    WHERE f2.feature_file = f.feature_file
                      AND f2.failure_reason = f.failure_reason
                      AND strftime('%Y-%W', r2.executed_at) = strftime('%Y-%W', r.executed_at)
                )
                ELSE 0
            END as weekly_recurrence
        FROM reports r
        LEFT JOIN failures f ON f.report_id = r.id
        WHERE {sql_where}
        ORDER BY r.executed_at DESC, f.feature_file
    """, params)

    return render_template_string(
        TEMPLATE,
        reports=reports,
        failure_rows=failure_rows,
        total=total,
        apps=apps,
        envs=envs,
        kpi=dict(runs=runs, passed=passed, failed=failed, avg_pct=avg_pct),
        recurring=recurring,
        chart_data=chart_data,
        recurring_threshold=RECURRING_FAILURE_THRESHOLD,
        feature_name_max=FEATURE_NAME_MAX,
        failure_reason_max=FAILURE_REASON_MAX,
        filters=dict(days=days, app=app_f, env=env_f),
    )


if __name__ == "__main__":
    print("🚀 Dashboard running → http://localhost:5000")
    app.run(debug=False, port=5000)
