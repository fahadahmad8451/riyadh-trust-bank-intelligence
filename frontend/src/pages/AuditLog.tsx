// Audit Log ("/audit", ADMIN only) — real GET /admin/audit-logs.
// Filters: action-type dropdown + user search. Route guard in App
// shows the Admin-only page to non-admins; the backend enforces it too.
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, roleLabel, type AuditRow } from '../api/client'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { TableSkeleton } from '../components/Skeleton'

const PAGE_SIZE = 100

const RESULT_BADGE: Record<string, string> = {
  SUCCESS: 'bg-emerald-100 text-emerald-800',
  DENIED: 'bg-red-100 text-red-800',
  FAILED: 'bg-red-100 text-red-800',
  ACCESS_DENIED: 'bg-red-100 text-red-800',
}

export default function AuditLog() {
  const navigate = useNavigate()
  const [rows, setRows] = useState<AuditRow[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionFilter, setActionFilter] = useState('ALL')
  const [userSearch, setUserSearch] = useState('')

  async function load(off: number) {
    setLoading(true)
    setError(null)
    try {
      const res = await api.auditLogs(PAGE_SIZE, off)
      setRows(res.data.audit_logs)
      setTotal(res.data.total)
      setOffset(off)
    } catch (e) {
      if (e instanceof Error && e.message === 'UNAUTHORIZED') {
        navigate('/login')
        return
      }
      setError(e instanceof Error ? e.message : 'Could not load the audit log')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const actions = useMemo(() => Array.from(new Set(rows.map((r) => r.action))).sort(), [rows])

  const filtered = useMemo(() => {
    const q = userSearch.trim().toLowerCase()
    return rows.filter(
      (r) =>
        (actionFilter === 'ALL' || r.action === actionFilter) &&
        (q === '' || (r.user ?? '').toLowerCase().includes(q)),
    )
  }, [rows, actionFilter, userSearch])

  return (
    <section>
      <h1 className="text-2xl font-bold text-navy-900">Audit Log</h1>
      <p className="mt-1 text-sm text-slate-600">
        Every login, question, upload and denied access — newest first. {total} entries in total.
      </p>

      <div className="mt-5 flex flex-wrap gap-3">
        <select
          value={actionFilter}
          onChange={(e) => setActionFilter(e.target.value)}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
          aria-label="Filter by action"
        >
          <option value="ALL">All actions</option>
          {actions.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <input
          type="search"
          value={userSearch}
          onChange={(e) => setUserSearch(e.target.value)}
          placeholder="Search by user email…"
          className="min-w-56 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
        />
      </div>

      <div className="mt-4">
        {loading && <TableSkeleton rows={8} cols={5} />}
        {!loading && error && <ErrorState message={error} onRetry={() => void load(offset)} />}
        {!loading && !error && rows.length === 0 && (
          <EmptyState title="No audit entries yet" message="Nothing has been logged yet." />
        )}
        {!loading && !error && rows.length > 0 && filtered.length === 0 && (
          <EmptyState
            title="No matches"
            message="No audit entries match your filters. Try a different action or user."
          />
        )}
        {!loading && !error && filtered.length > 0 && (
          <>
            <div className="overflow-x-auto rounded-xl border bg-white shadow-sm">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-slate-50 text-left">
                    <th className="px-4 py-3 font-semibold text-navy-900">Time</th>
                    <th className="px-4 py-3 font-semibold text-navy-900">User</th>
                    <th className="px-4 py-3 font-semibold text-navy-900">Role</th>
                    <th className="px-4 py-3 font-semibold text-navy-900">Action</th>
                    <th className="px-4 py-3 font-semibold text-navy-900">Result</th>
                    <th className="px-4 py-3 font-semibold text-navy-900">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row, i) => (
                    <tr key={`${row.ts}-${i}`} className="border-b last:border-0">
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-600">
                        {new Date(row.ts).toLocaleString()}
                      </td>
                      <td className="px-4 py-3">{row.user ?? '—'}</td>
                      <td className="px-4 py-3">
                        {row.role ? (
                          <span className="rounded-full bg-navy-100 px-2 py-0.5 text-xs font-medium text-navy-800">
                            {roleLabel(row.role)}
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="px-4 py-3 font-medium">{row.action}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${RESULT_BADGE[row.result] ?? 'bg-slate-100 text-slate-700'}`}
                        >
                          {row.result}
                        </span>
                      </td>
                      <td className="max-w-xs truncate px-4 py-3 text-xs text-slate-600" title={row.detail ?? row.resource ?? ''}>
                        {row.detail ?? row.resource ?? '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex items-center gap-3 text-sm text-slate-600">
              <button
                type="button"
                disabled={offset === 0 || loading}
                onClick={() => void load(Math.max(0, offset - PAGE_SIZE))}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 font-medium hover:bg-slate-50 disabled:opacity-50"
              >
                ← Newer
              </button>
              <span>
                Showing {offset + 1}–{offset + rows.length} of {total}
              </span>
              <button
                type="button"
                disabled={offset + rows.length >= total || loading}
                onClick={() => void load(offset + PAGE_SIZE)}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 font-medium hover:bg-slate-50 disabled:opacity-50"
              >
                Older →
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
