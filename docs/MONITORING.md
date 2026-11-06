# Monitoring — v0.9 (Project 1, LAST step)

Project 1 is now complete end-to-end: Requirements → Estimate →
Design → Setup → Development (Sprints 1–4) → Testing → Staging →
Production → **Monitoring**.

Monitoring here is **local-first, $0, no external service**: no
Grafana Cloud, no PagerDuty, no Sentry SaaS, no Telegram bot.
Metrics and alerts are files in the data directory, and the Admin
sees them in the **Monitoring** page (`/monitoring`, Admin only).
If nobody looks at the dashboard, nobody is paged — that is the
honest limit of a $0 setup (see §6 for what external alerting
would need).

## 1. What is monitored

Every request the API serves is recorded by middleware
(`app/main.py`) into **`metrics.jsonl`** (one JSON object per line):
timestamp, endpoint (id-like segments collapsed to `{id}`), method,
HTTP status, latency in ms, and the caller's role (from the access
token; public requests have no role). No question text, no user
content, no tokens, no passwords are ever recorded.

Sources the dashboard and reports combine:

| Source | What it tells us |
|---|---|
| `metrics.jsonl` | Requests, error rate, latency p50/p95, chats, top endpoints, per-hour buckets |
| `audit.jsonl` | Failed logins, RBAC denials (ACCESS_DENIED + refused chats) |
| `feedback.jsonl` | Thumbs up/down totals |
| `alerts.jsonl` | Alerts fired, acknowledged or still active |
| `/api/v1/health` | API up/down, uptime, vector store, generation mode, embeddings |

Endpoints (all ADMIN only — non-admins get 403 + ACCESS_DENIED
audit, exactly like the other admin routes):

| Endpoint | Returns |
|---|---|
| `GET /api/v1/admin/metrics` | Summary: totals, by endpoint/status, error rate, latency p50/p95 (all + chat), chats, RBAC refusals, failed logins, feedback, uptime |
| `GET /api/v1/admin/metrics/timeseries?hours=24` | Per-hour buckets (requests, 5xx, chats, p95) for the last N hours (1–168) |
| `GET /api/v1/admin/monitoring/overview` | Health + summary + disk usage + data-dir size + alert counts + 5 newest 5xx |
| `GET /api/v1/admin/monitoring/recent-errors?limit=20` | Newest 5xx requests |
| `GET /api/v1/admin/alerts?status=active` | Alerts, newest first |
| `POST /api/v1/admin/alerts/{id}/acknowledge` | Mark an alert acknowledged (records who and when) |

## 2. Alert rules

Rules live in `backend/app/monitoring/alert_rules.py` (pure
functions — tests feed them synthetic data and prove each rule
fires AND does not fire below its threshold). The checker is
`scripts/monitor_check.py`; the store is `backend/app/core/monitoring.py`.

| Rule | Threshold | Severity | What to do |
|---|---|---|---|
| `brute_force` | 10+ failed logins in 5 min | HIGH | Check the audit log for source IPs. The login rate limiter (5 failed/min per email, v0.8) already slows the attacker. Consider blocking the IP at the firewall. |
| `error_rate` | 5xx rate > 5% over the last hour (min 20 requests) | HIGH | Check Recent errors + API logs; find the failing endpoint and when it first failed. |
| `p95_latency` | Chat p95 latency > 10 s over the last hour | MEDIUM | Usually the cross-encoder reranker on a low-RAM machine. Test `RTB_RERANKER=off` (see docs/PRODUCTION.md §4) and compare. **Caveat:** the rule has no minimum-sample guard — with only 2 chats (first one a 26 s cold start) it fires. Treat a p95 alert on <5 chats as "check, don't panic". |
| `rbac_spike` | > 20 RBAC denials in 1 hour | MEDIUM | See which users/roles are denied — an attack probe, or a role that legitimately needs more access (Admin can raise the role). |
| `api_down` | Health endpoint unreachable or status ≠ ok | CRITICAL | Restart the API (`scripts/production_start.sh` / `.ps1`). If it fails to start, read the startup error — a weak SECRET_KEY or wildcard CORS refuses to start by design. |
| `disk_usage` | Disk used > 80% | MEDIUM | Run `scripts/rotate_logs.py` to archive old logs; delete old backups in `backups/`. |

**Dedup:** the same rule does not create a second ACTIVE alert
inside 30 minutes (the checker prints the existing one instead).
Acknowledging an alert records who saw it — it does **not** fix
the problem.

**Exit codes of `monitor_check.py`:** 0 = healthy, no active
alert; 1 = at least one active alert (HIGH/MEDIUM); 2 = CRITICAL
alert active, or the API is down.

## 3. Scheduler — every 5 minutes (check) + daily (report)

This VM does **not** create a scheduled task — Fahad's PC is a
different machine. Set it up there:

**Windows — Task Scheduler (PowerShell, run as Administrator):**

```powershell
# Every 5 minutes: alert check (production API :8000, data-prod)
$action = New-ScheduledTaskAction -Execute "C:\path\to\venv\Scripts\python.exe" `
  -Argument "scripts\monitor_check.py --port 8000 --data-dir data-prod" `
  -WorkingDirectory "C:\path\to\riyadh-trust-bank-intelligence"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "RTB Monitor Check" -Action $action -Trigger $trigger

# Daily 08:00: daily report
$action2 = New-ScheduledTaskAction -Execute "C:\path\to\venv\Scripts\python.exe" `
  -Argument "scripts\daily_report.py --data-dir data-prod" `
  -WorkingDirectory "C:\path\to\riyadh-trust-bank-intelligence"
$trigger2 = New-ScheduledTaskTrigger -Daily -At 08:00
Register-ScheduledTask -TaskName "RTB Daily Report" -Action $action2 -Trigger $trigger2
```

**Linux — cron:**

```cron
*/5 * * * * cd ~/riyadh-trust-bank-intelligence && ~/rtb-prod-venv/bin/python scripts/monitor_check.py --port 8000 --data-dir data-prod >> logs/monitor.log 2>&1
0 8 * * * cd ~/riyadh-trust-bank-intelligence && ~/rtb-prod-venv/bin/python scripts/daily_report.py --data-dir data-prod >> logs/monitor.log 2>&1
0 3 * * 0 cd ~/riyadh-trust-bank-intelligence && ~/rtb-prod-venv/bin/python scripts/rotate_logs.py --data-dir data-prod >> logs/monitor.log 2>&1
```

Staging equivalent: `--port 8001 --data-dir data-staging`.

## 4. Daily report

`scripts/daily_report.py` builds a Markdown summary of the last
24 hours (requests, chats, 5xx, latency p50/p95, top endpoints,
failed logins, RBAC denials, feedback, alerts fired) from the real
files and writes it to `<data-dir>/reports/daily-YYYY-MM-DD.md`.
Counts only — no question text, no PII. No email is sent (there
is no SMTP); the report is a file, and the Monitoring page notes
where it lives.

## 5. Retention policy

`scripts/rotate_logs.py` (run weekly, or by hand):

- A JSONL log (`metrics.jsonl`, `audit.jsonl`, `alerts.jsonl`,
  `conversations.jsonl`) over **10,000 lines** is rotated: the
  oldest lines move into `archives/<name>-YYYYMMDD-HHMMSS.jsonl.gz`
  and the live file keeps the newest **5,000** lines.
- At most **7 archives** per file are kept; older ones are deleted.
- Roughly 35k–70k lines of history per log. The live file is never
  deleted — only archives and old archives.
- The request-metrics writer rotates the same way when the file
  passes 10,000 lines (checked only once the file is > 1 MB, so
  normal requests stay fast).

## 6. What monitoring does NOT do (honest limits)

- **No external alerting.** Nobody is woken up at night: no email,
  SMS, phone call or Telegram message. To add it you would need an
  SMTP account (email), a Twilio-style account (SMS, paid), or a
  Telegram bot token + chat id (free, but the bot must run
  somewhere). The alert file already has everything such a sender
  would need (rule, severity, message, timestamp).
- **No uptime history beyond the files.** Uptime is "seconds since
  this process started"; a restart resets it. The metrics file is
  the real record of when the API was serving.
- **p95 on tiny samples is noisy** (see the `p95_latency` caveat
  in §2). On this RAM-starved VM, English chat latency is 4–8 s
  steady-state and the first chat after a cold start can take
  25 s+ — the target (< 3 s) is still missed here; the real
  decision belongs on Fahad's PC (see §8).
- **Alerts are only as good as the checker running.** If the
  scheduled task is not set up on Fahad's PC, no alert will ever
  fire — the dashboard will simply show old data. Check the
  "Last updated" time on the Monitoring page.

## 7. Live verification (this VM, 2026-11-06 ~03:20 PKT)

- **Pytest: 99 passed, 0 failed** in BOTH venvs (prod + staging) —
  81 previous + 18 new `tests/test_monitoring.py` (metrics
  recording + role, summary auth 403/401, timeseries, alerts +
  acknowledge, every rule firing AND below threshold, cooldown
  dedup, monitor_check exit 2 on a dead port, rotation).
- **Frontend builds PASS** (dev + staging, zero tsc errors;
  production build with `VITE_API_URL=http://127.0.0.1:8000`).
- **Live production API :8000 + web :3000**, real traffic
  (9/9 checks): register → login → EN chat (5 citations) →
  RBAC refusal (service AML question → refused, 0 citations) →
  10 failed logins (10 different emails, all 401) → admin login →
  `/admin/metrics` (16 requests) → overview → timeseries (25 buckets).
- **`monitor_check.py` exit 1** with 2 REAL alerts: `[HIGH]
  brute_force` (10 failed logins in 5 min) and `[MEDIUM]
  p95_latency` (chat p95 26.3 s over the last hour — 2 chats, first
  one a cold start). Second run created NO duplicates (cooldown) —
  alerts file stayed at 2 lines.
- **Acknowledge works live:** brute_force acknowledged via the API
  (200, acknowledged by mon-admin@rtb.local); overview then showed
  1 active alert, 26 failed logins total, 2 RBAC refusals, disk 7%.
- **Daily report written:** `data-prod/reports/daily-2026-11-05.md`
  (25 requests, 2 chats, 0 errors, 26 failed logins, 2 RBAC
  denials, 2 alerts).
- **Rotation live:** all 4 logs under 10k lines — "no rotation
  needed" (rotation itself is proven by pytest with synthetic data).
- **Monitoring page screenshot:** `docs/screenshots/05-monitoring.png`
  — real cards (34 requests, 26.26 s chat p95, 26 failed logins,
  1 active alert), hourly bar chart, alerts table, system info
  (disk 7%, v0.9.0 · production, extractive-fallback, MiniLM 384-dim).
  Two bugs the screenshot caught and fixed: version/environment
  showed "undefined" (overview did not include them) and the chart
  bars were invisible (% heights in an auto-height flex column —
  now pixel heights).
- **Cleanup:** the two verification users (mon-admin, mon-user)
  were deleted from `data-prod/users.json` afterwards — it is back
  to only `prod-admin@rtb.local`. Metrics, alerts and the daily
  report were KEPT: they are the honest record of this verification
  traffic. (Their refresh tokens were removed too.)

## 8. Project 1 — final PC-only pending list

These were never DONE on this VM and are still waiting on Fahad's PC
(from Testing / Staging / Production, unchanged by Monitoring):

1. **Ollama + llama3.1:8b** — install on the PC; until then answers
   stay in extractive-fallback mode.
2. **PgVector test** against local PostgreSQL on port 5432 (the
   code path exists; it has never run against a real Postgres).
3. **English latency decision** — re-measure on the PC (more RAM)
   and decide on the cross-encoder (`RTB_RERANKER=off` flag exists
   for the one-command test). VM steady-state is 4–8 s vs the < 3 s
   target; first-chat cold start 25 s+.
4. **Full 20-question eval** on production data (faithfulness /
   recall / relevancy with a real LLM).
5. **Arabic garbling / relevancy decision** — relevancy 0.42–0.61
   (MiniLM is English-only); the real fix needs BGE-M3 + a real LLM.
6. **httpOnly cookies** — tokens still live in localStorage; this
   is still production's biggest remaining weakness.
7. **Password reset** — "forgot password" honestly says to contact
   the Admin; no reset flow exists.
8. **RBAC refusal is not guaranteed on every AML-like phrasing**
   (v0.8 note): "AML policy for high-risk customers?" returned 5
   RETAIL citations — no leak, but no refusal either. Question-
   dependent behaviour since Sprint 4.

Everything else in the process is DONE: Requirements, Estimate,
Design, Setup, Sprints 1–4, Testing, Staging, Production,
Monitoring. **Project 1 is complete on this VM; the 8 items above
are the PC handover list.**
