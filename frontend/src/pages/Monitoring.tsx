// Monitoring ("/monitoring", ADMIN only) — v0.9.
// Live cards (API status, requests, error rate, p95 latency, chats,
// RBAC refusals, failed logins), per-hour request chart (CSS bars,
// real timeseries data), alerts table with acknowledge, recent 5xx
// errors, and system info (disk, data dir size, version, env,
// generation mode, embeddings). Auto-refresh every 30 s with a
// toggle. Every number comes from the backend — no sample data.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  api,
  type AlertRow,
  type MonitoringOverview,
  type TimeseriesBucket,
} from '../api/client'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { CardSkeleton, TableSkeleton } from '../components/Skeleton'
import { useToast } from '../components/Toast'

const SEVERITY_BADGE: Record<string, string> = {
  CRITICAL: 'bg-red-600 text-white',
  HIGH: 'bg-red-100 text-red-800',
  MEDIUM: 'bg-amber-100 text-amber-800',
}

function fmtLatency(ms: number | null): string {
  if (ms === null || ms === undefined) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`
}

function fmtUptime(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-bold text-navy-900">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  )
}

export default function Monitoring() {
  const navigate = useNavigate()
  const toast = useToast()
  const [overview, setOverview] = useState<MonitoringOverview | null>(null)
  const [buckets, setBuckets] = useState<TimeseriesBucket[]>([])
  const [alerts, setAlerts] = useState<AlertRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [ackBusy, setAckBusy] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true)
      setError(null)
      try {
        const [ov, ts, al] = await Promise.all([
          api.monitoringOverview(),
          api.monitoringTimeseries(24),
          api.monitoringAlerts(),
        ])
        setOverview(ov.data)
        setBuckets(ts.data.buckets)
        setAlerts(al.data.alerts)
        setLastUpdated(new Date())
      } catch (e) {
        if (e instanceof Error && e.message === 'UNAUTHORIZED') {
          navigate('/login')
          return
        }
        setError(e instanceof Error ? e.message : 'Could not load monitoring data')
      } finally {
        if (!silent) setLoading(false)
      }
    },
    [navigate],
  )

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (timer.current) clearInterval(timer.current)
    if (autoRefresh) {
      timer.current = setInterval(() => void load(true), 30_000)
    }
    return () => {
      if (timer.current) clearInterval(timer.current)
    }
  }, [autoRefresh, load])

  async function acknowledge(id: string) {
    setAckBusy(id)
    try {
      await api.acknowledgeAlert(id)
      setAlerts((prev) =>
        prev.map((a) => (a.id === id ? { ...a, status: 'acknowledged' } : a)),
      )
      toast.toast('Alert acknowledged', 'success')
      void load(true)
    } catch (e) {
      toast.toast(e instanceof Error ? e.message : 'Could not acknowledge the alert', 'error')
    } finally {
      setAckBusy(null)
    }
  }

  const s = overview?.summary
  const activeAlerts = alerts.filter((a) => a.status === 'active')
  const maxBucket = Math.max(1, ...buckets.map((b) => b.requests))

  return (
    <section>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-navy-900">Monitoring</h1>
          <p className="mt-1 text-sm text-slate-600">
            Live health, traffic, errors and alerts — all recorded by this API, nothing sampled.
            {lastUpdated && (
              <span className="text-slate-500">
                {' '}
                Last updated {lastUpdated.toLocaleTimeString()}.
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="h-4 w-4 accent-navy-900"
            />
            Auto-refresh (30s)
          </label>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-navy-900 hover:bg-slate-50"
          >
            Refresh now
          </button>
        </div>
      </div>

      {loading && (
        <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      )}
      {!loading && error && (
        <div className="mt-5">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      )}

      {!loading && !error && overview && s && (
        <>
          <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard
              label="API status"
              value={overview.health.status === 'ok' ? 'Online' : 'Down'}
              sub={`uptime ${fmtUptime(s.uptime_seconds)} · v${overview.health.version} · ${overview.health.environment}`}
            />
            <StatCard label="Requests (all time)" value={String(s.total_requests)} sub={`${s.chats_total} chats`} />
            <StatCard
              label="Error rate (5xx)"
              value={`${(s.error_rate_5xx * 100).toFixed(2)}%`}
              sub={`${s.errors_5xx} errors · ${s.errors_4xx} client errors (4xx)`}
            />
            <StatCard
              label="Chat p95 latency"
              value={fmtLatency(s.chat_latency_ms_p95)}
              sub={`p50 ${fmtLatency(s.chat_latency_ms_p50)} · all-endpoint p95 ${fmtLatency(s.latency_ms_p95)}`}
            />
            <StatCard label="RBAC refusals" value={String(s.rbac_refusals_total)} sub="denied access + refused chats" />
            <StatCard label="Failed logins" value={String(s.failed_logins_total)} sub="all time" />
            <StatCard
              label="Feedback"
              value={String(s.feedback_total)}
              sub={s.feedback_total ? `${s.feedback_up} up · ${s.feedback_down} down` : 'no feedback yet'}
            />
            <StatCard
              label="Active alerts"
              value={String(overview.alerts_active)}
              sub={`${overview.alerts_critical_active} critical · ${overview.alerts_high_active} high · ${overview.alerts_total} total`}
            />
          </div>

          {/* Hourly traffic chart */}
          <div className="mt-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="text-base font-bold text-navy-900">Requests per hour — last 24 hours</h2>
            {buckets.every((b) => b.requests === 0) ? (
              <div className="mt-3">
                <EmptyState
                  title="No requests in the last 24 hours"
                  message="The API has not served any requests in this window — it may not have been running, or no one used it."
                />
              </div>
            ) : (
              <div className="mt-4 flex h-36 items-end gap-1">
                {buckets.map((b) => (
                  <div
                    key={b.hour}
                    // Pixel heights, not %: a % height inside an
                    // auto-height flex column resolves to 0 and the
                    // bars were invisible (caught by the screenshot).
                    className="flex flex-1 flex-col items-center justify-end"
                    title={`${new Date(b.hour).toLocaleString()} — ${b.requests} requests, ${b.errors_5xx} errors, ${b.chats} chats, p95 ${fmtLatency(b.p95_ms)}`}
                  >
                    <div
                      className={`w-full rounded-t ${b.errors_5xx > 0 ? 'bg-red-400' : 'bg-navy-700'}`}
                      style={{ height: `${Math.max(2, (b.requests / maxBucket) * 120)}px` }}
                    />
                    <p className="mt-1 text-center text-[10px] text-slate-400">
                      {new Date(b.hour).getHours()}:00
                    </p>
                  </div>
                ))}
              </div>
            )}
            <p className="mt-2 text-xs text-slate-500">
              Red bars contain 5xx errors. Hover a bar for the exact counts. The tallest bar is the
              busiest hour.
            </p>
          </div>

          {/* Alerts */}
          <div className="mt-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="text-base font-bold text-navy-900">Alerts</h2>
            {alerts.length === 0 ? (
              <div className="mt-3">
                <EmptyState
                  title="No alerts"
                  message="No alert rule has fired yet. Rules are checked every 5 minutes by scripts/monitor_check.py — see docs/MONITORING.md."
                />
              </div>
            ) : (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-slate-50 text-left">
                      <th className="px-3 py-2 font-semibold text-navy-900">Severity</th>
                      <th className="px-3 py-2 font-semibold text-navy-900">Rule</th>
                      <th className="px-3 py-2 font-semibold text-navy-900">Message</th>
                      <th className="px-3 py-2 font-semibold text-navy-900">Time</th>
                      <th className="px-3 py-2 font-semibold text-navy-900">Status</th>
                      <th className="px-3 py-2 font-semibold text-navy-900">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alerts.map((a) => (
                      <tr key={a.id} className="border-b last:border-0">
                        <td className="px-3 py-2">
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs font-medium ${SEVERITY_BADGE[a.severity] ?? 'bg-slate-100 text-slate-700'}`}
                          >
                            {a.severity}
                          </span>
                        </td>
                        <td className="px-3 py-2 font-mono text-xs">{a.rule}</td>
                        <td className="px-3 py-2">{a.message}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-600">
                          {new Date(a.ts).toLocaleString()}
                        </td>
                        <td className="px-3 py-2">
                          {a.status === 'active' ? (
                            <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
                              Active
                            </span>
                          ) : (
                            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                              Acknowledged{a.acknowledged_by ? ` by ${a.acknowledged_by}` : ''}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          {a.status === 'active' && (
                            <button
                              type="button"
                              disabled={ackBusy === a.id}
                              onClick={() => void acknowledge(a.id)}
                              className="rounded-lg border border-slate-300 px-2.5 py-1 text-xs font-medium text-navy-900 hover:bg-slate-50 disabled:opacity-50"
                            >
                              {ackBusy === a.id ? 'Saving…' : 'Acknowledge'}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {activeAlerts.length > 0 && (
              <p className="mt-2 text-xs text-slate-500">
                {activeAlerts.length} active alert(s). Acknowledging marks that you have seen it —
                it does not fix the underlying problem (see the runbook in docs/MONITORING.md).
              </p>
            )}
          </div>

          {/* Recent errors + system info */}
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="text-base font-bold text-navy-900">Recent errors (5xx)</h2>
              {overview.recent_errors.length === 0 ? (
                <div className="mt-3">
                  <EmptyState title="No 5xx errors" message="No server error has been recorded yet." />
                </div>
              ) : (
                <ul className="mt-3 space-y-2 text-sm">
                  {overview.recent_errors.map((e, i) => (
                    <li key={`${e.ts}-${i}`} className="flex items-center justify-between gap-2 border-b pb-2 last:border-0">
                      <span className="font-mono text-xs">
                        {e.method} {e.endpoint}
                      </span>
                      <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
                        {e.status}
                      </span>
                      <span className="whitespace-nowrap text-xs text-slate-500">
                        {new Date(e.ts).toLocaleTimeString()} · {fmtLatency(e.latency_ms)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="text-base font-bold text-navy-900">System</h2>
              <dl className="mt-3 space-y-2 text-sm">
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Disk used</dt>
                  <dd className="font-medium">
                    {overview.disk.used_percent ?? '—'}% ({overview.disk.used_gb} / {overview.disk.total_gb} GB,{' '}
                    {overview.disk.free_gb} GB free)
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Data directory size</dt>
                  <dd className="font-medium">{overview.data_dir_mb ?? '—'} MB</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Version / environment</dt>
                  <dd className="font-medium">
                    v{overview.health.version} · {overview.health.environment}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Generation mode</dt>
                  <dd className="font-medium">{overview.health.generation_mode ?? '—'}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Embeddings</dt>
                  <dd className="font-medium">
                    {overview.health.embeddings?.model ?? '—'}
                    {overview.health.embeddings?.dim ? ` (${overview.health.embeddings.dim}-dim)` : ''}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Vector store</dt>
                  <dd className="font-medium">
                    {overview.health.vector_store?.status ?? '—'} ·{' '}
                    {overview.health.vector_store?.documents ?? '—'} docs,{' '}
                    {overview.health.vector_store?.chunks ?? '—'} chunks
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Demo accounts</dt>
                  <dd className="font-medium">
                    {overview.health.demo_accounts_enabled ? 'Enabled' : 'Disabled'}
                  </dd>
                </div>
              </dl>
              <p className="mt-3 text-xs text-slate-500">
                Daily reports land in the data directory under reports/ (scripts/daily_report.py).
                There is no external alerting — no email, SMS or phone call (see
                docs/MONITORING.md for what that would need).
              </p>
            </div>
          </div>
        </>
      )}

      {!loading && !error && !overview && <TableSkeleton rows={6} cols={4} />}
    </section>
  )
}
