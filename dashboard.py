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
    body { background:#0d1117; color:#c9d1d9; font-family:'Segoe UI',sans-serif; }
    .card { background:#161b22; border:1px solid #30363d; border-radius:8px; }
    .kpi  { text-align:center; padding:20px; }
    .kpi .val { font-size:2.2rem; font-weight:700; }
    .pass { color:#3fb950; } .fail { color:#f85149; }
    .warn { color:#d29922; } .info { color:#58a6ff; }
    th   { color:#8b949e; font-size:.75rem; text-transform:uppercase; }
    tr:hover { background:#1f2937 !important; }
    a    { color:#58a6ff; }
    .pill      { border-radius:4px; padding:2px 8px; font-size:.72rem; }
    .pill-fail { background:#3d1a1a; color:#f85149; }
    .pill-pass { background:#1a3d1e; color:#3fb950; }
    .pill-warn { background:#3d2600; color:#d29922; }
  </style>
</head>
<body>

<nav class="navbar" style="background:#161b22;border-bottom:1px solid #30363d;padding:10px 20px">
  <span class="fw-bold fs-5">🧪 Regression Dashboard</span>
  <span class="text-muted small ms-auto">{{ total }} total runs in DB</span>
</nav>

<!-- Filters -->
<div style="background:#161b22;border-bottom:1px solid #30363d;padding:10px 20px">
  <form method="get" class="d-flex gap-2 flex-wrap align-items-center">
    <select name="days" class="form-select form-select-sm bg-dark text-light border-secondary" style="width:auto">
      {% for d in [1,3,7,14,30] %}
      <option value="{{d}}" {{'selected' if filters.days==d}}>Last {{d}} day{{'s' if d>1}}</option>
      {% endfor %}
    </select>
    <select name="app" class="form-select form-select-sm bg-dark text-light border-secondary" style="width:auto">
      <option value="">All Apps</option>
      {% for a in apps %}<option {{'selected' if filters.app==a}}>{{a}}</option>{% endfor %}
    </select>
    <select name="env" class="form-select form-select-sm bg-dark text-light border-secondary" style="width:auto">
      <option value="">All Envs</option>
      {% for e in envs %}<option {{'selected' if filters.env==e}}>{{e}}</option>{% endfor %}
    </select>
    <button class="btn btn-sm btn-outline-info">Apply</button>
    <a href="/" class="btn btn-sm btn-outline-secondary">Reset</a>
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
        <div class="text-muted small mb-2">📈 Daily Pass / Fail Trend</div>
        <canvas id="chart" height="100"></canvas>
      </div>
    </div>
    <!-- Top Failures -->
    <div class="col-md-4">
      <div class="card p-3 h-100">
        <div class="text-muted small mb-2">🔥 Most Failed (This Period)</div>
        {% for r in top_failed %}
        <div class="d-flex justify-content-between align-items-center mb-2">
          <span class="small">{{r['application']}} · {{r['env']}}</span>
          <span class="pill pill-fail">{{r['fail_count']}}x</span>
        </div>
        {% else %}
        <div class="text-muted small text-center mt-3">🎉 No failures!</div>
        {% endfor %}
      </div>
    </div>
  </div>

  <!-- Execution Table -->
  <div class="card p-3 mb-4">
    <div class="text-muted small mb-3">📋 Execution History</div>
    <div class="table-responsive">
      <table class="table table-sm table-dark table-borderless align-middle">
        <thead><tr>
          <th>Date / Time</th>
          <th>Application</th>
          <th>Env</th>
          <th>DS Row</th>
          <th>Job</th>
          <th>Branch</th>
          <th>Triggered By</th>
          <th>Passed</th>
          <th>Failed</th>
          <th>Pass %</th>
          <th>Duration</th>
          <th>Reports</th>
        </tr></thead>
        <tbody>
        {% for r in reports %}
        <tr>
          <td class="small">{{r['executed_at'][:16].replace('T',' ')}}</td>
          <td><strong>{{r['application']}}</strong></td>
          <td><span class="pill pill-warn">{{r['env']}}</span></td>
          <td class="text-center">{{r['ds_row']}}</td>
          <td class="small text-muted" title="{{r['job_name']}}">
            {{r['job_name'][:25]}}{{'…' if r['job_name'] and r['job_name']|length>25 else ''}}
          </td>
          <td class="small">{{r['source_branch']}}</td>
          <td class="small text-muted">{{r['triggered_by']}}</td>
          <td class="pass">{{r['scenarios_passed']}}</td>
          <td class="{{'fail' if r['scenarios_failed']>0 else 'pass'}}">
            <strong>{{r['scenarios_failed']}}</strong>
          </td>
          <td class="{{'pass' if r['pass_percent']>=95 else 'warn' if r['pass_percent']>=80 else 'fail'}}">
            {{r['pass_percent']}}%
          </td>
          <td class="small text-muted">{{r['duration']}}</td>
          <td class="small">
            {% if r['karate_url'] %}
              <a href="{{r['karate_url']}}" target="_blank">Karate</a>
            {% endif %}
            {% if r['cluecumber_url'] %}
              <a href="{{r['cluecumber_url']}}" target="_blank">Clue</a>
            {% endif %}
            {% if r['cucumber_url'] %}
              <a href="{{r['cucumber_url']}}" target="_blank">Cuke</a>
            {% endif %}
            {% if r['pipeline_id'] %}
              <a href="#" target="_blank">Pipeline</a>
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
      { label: 'Passed', data: data.map(d => d.passed), backgroundColor: '#3fb950' },
      { label: 'Failed', data: data.map(d => d.failed), backgroundColor: '#f85149' }
    ]
  },
  options: {
    responsive: true,
    plugins: { legend: { labels: { color: '#c9d1d9' } } },
    scales: {
      x: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } },
      y: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } }
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

    where  = ["executed_at >= ?"]
    params = [cutoff]
    if app_f: where.append("application = ?"); params.append(app_f)
    if env_f: where.append("env = ?");         params.append(env_f)
    sql_where = " AND ".join(where)

    reports    = query(f"SELECT * FROM reports WHERE {sql_where} ORDER BY executed_at DESC", params)
    total      = query("SELECT COUNT(*) as c FROM reports")[0]["c"]
    apps       = [r["application"] for r in query("SELECT DISTINCT application FROM reports WHERE application != ''")]
    envs       = [r["env"]         for r in query("SELECT DISTINCT env FROM reports WHERE env != ''")]

    kpi_rows   = query(f"SELECT * FROM reports WHERE {sql_where}", params)
    runs       = len(kpi_rows)
    passed     = sum(r["scenarios_passed"] for r in kpi_rows)
    failed     = sum(r["scenarios_failed"] for r in kpi_rows)
    avg_pct    = round(sum(r["pass_percent"] for r in kpi_rows) / runs, 1) if runs else 0

    top_failed = query(f"""
        SELECT application, env, COUNT(*) as fail_count
        FROM reports WHERE {sql_where} AND scenarios_failed > 0
        GROUP BY application, env ORDER BY fail_count DESC LIMIT 6
    """, params)

    chart_rows = query(f"""
        SELECT date(executed_at) as date,
               SUM(scenarios_passed) as passed,
               SUM(scenarios_failed) as failed
        FROM reports WHERE {sql_where}
        GROUP BY date(executed_at) ORDER BY date
    """, params)
    chart_data = [{"date": r["date"], "passed": r["passed"], "failed": r["failed"]}
                  for r in chart_rows]

    return render_template_string(
        TEMPLATE,
        reports=reports,
        total=total,
        apps=apps,
        envs=envs,
        kpi=dict(runs=runs, passed=passed, failed=failed, avg_pct=avg_pct),
        top_failed=top_failed,
        chart_data=chart_data,
        filters=dict(days=days, app=app_f, env=env_f),
    )


if __name__ == "__main__":
    print("🚀 Dashboard running → http://localhost:5000")
    app.run(debug=False, port=5000)
