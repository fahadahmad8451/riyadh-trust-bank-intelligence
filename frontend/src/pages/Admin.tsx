// Admin ("/admin", ADMIN only) — real data only: users (GET
// /admin/users) with role changes (PUT role endpoint), feedback stats,
// and system status cards (health + metrics + last generation mode +
// the honest embeddings-model label from SPRINT1).
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  api,
  getStoredUser,
  ROLES,
  roleLabel,
  type FeedbackStats,
  type HealthResponse,
  type MetricsResponse,
  type PasswordResetRequestRow,
  type Role,
  type User,
} from '../api/client'
import EvalDashboard from '../components/EvalDashboard'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { TableSkeleton } from '../components/Skeleton'
import { useToast } from '../components/Toast'

export default function Admin() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const me = getStoredUser()
  const [users, setUsers] = useState<User[]>([])
  const [feedback, setFeedback] = useState<FeedbackStats | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pendingRole, setPendingRole] = useState<{ user: User; role: Role } | null>(null)
  const [changing, setChanging] = useState(false)
  // v0.10: password reset — pending forgot-password requests, plus
  // the admin's "set a new temporary password" dialog.
  const [resetRequests, setResetRequests] = useState<PasswordResetRequestRow[]>([])
  const [resetTarget, setResetTarget] = useState<{ email: string } | null>(null)
  const [resetPassword, setResetPassword] = useState('')
  const [resetConfirm, setResetConfirm] = useState('')
  const [resetting, setResetting] = useState(false)
  const lastMode = (() => {
    try {
      return localStorage.getItem('rtb_last_generation_mode')
    } catch {
      return null
    }
  })()

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const [u, f, h, m, r] = await Promise.all([
        api.adminUsers(),
        api.feedbackStats(),
        api.health(),
        api.metrics(),
        api.passwordResetRequests('pending'),
      ])
      setUsers(u.data.users)
      setFeedback(f.data)
      setHealth(h)
      setMetrics(m)
      setResetRequests(r.data.requests)
    } catch (e) {
      if (e instanceof Error && e.message === 'UNAUTHORIZED') {
        navigate('/login')
        return
      }
      setError(e instanceof Error ? e.message : 'Could not load admin data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function confirmRoleChange() {
    if (!pendingRole) return
    setChanging(true)
    try {
      await api.changeUserRole(pendingRole.user.email, pendingRole.role)
      toast(
        `${pendingRole.user.email} is now ${roleLabel(pendingRole.role)}.`,
        'success',
      )
      setPendingRole(null)
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Role could not be changed.', 'error')
    } finally {
      setChanging(false)
    }
  }

  async function confirmPasswordReset() {
    if (!resetTarget) return
    if (resetPassword !== resetConfirm) {
      toast('Passwords do not match.', 'error')
      return
    }
    setResetting(true)
    try {
      await api.resetUserPassword(resetTarget.email, resetPassword, resetConfirm)
      toast(
        `Password reset for ${resetTarget.email}. Give them the new temporary password directly — their old sessions are revoked.`,
        'success',
      )
      setResetTarget(null)
      setResetPassword('')
      setResetConfirm('')
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Password could not be reset.', 'error')
    } finally {
      setResetting(false)
    }
  }

  async function dismissResetRequest(id: string) {
    try {
      await api.dismissPasswordResetRequest(id)
      toast('Reset request dismissed.', 'success')
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Request could not be dismissed.', 'error')
    }
  }

  const statusCard = (label: string, value: string, sub?: string) => (
    <div className="rounded-xl border bg-white p-4 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-bold text-navy-900">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  )

  return (
    <section>
      <h1 className="text-2xl font-bold text-navy-900">Admin</h1>
      <p className="mt-1 text-sm text-slate-600">
        Users, evaluation, feedback and system status — all from the live API.
        {me ? ` Signed in as ${me.email} (${roleLabel(me.role)}).` : ''}
      </p>

      {loading && <TableSkeleton rows={6} cols={4} />}
      {!loading && error && <ErrorState message={error} onRetry={() => void load()} />}
      {!loading && !error && (
        <div className="mt-5 space-y-8">
          {/* System status */}
          <div>
            <h2 className="text-lg font-semibold text-navy-900">System status</h2>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {statusCard(
                'Backend health',
                health ? health.data.status : 'unknown',
                health ? `${health.data.service} · v${health.data.version}` : undefined,
              )}
              {statusCard(
                'Environment',
                health ? health.data.environment : 'unknown',
                metrics ? `uptime ${Math.round(metrics.data.uptime_seconds / 60)} min` : undefined,
              )}
              {statusCard(
                'Generation mode',
                lastMode ?? 'No chat yet',
                lastMode === 'extractive-fallback'
                  ? 'Answers are grounded extracts — no LLM running on this VM'
                  : lastMode === 'ollama'
                    ? 'Answers are generated by the local LLM (Ollama)'
                    : undefined,
              )}
              {statusCard(
                'Embeddings model',
                'all-MiniLM-L6-v2',
                '384-dim — recorded fallback (BGE-M3 not available on this VM, see SPRINT1)',
              )}
            </div>
          </div>

          {/* Users */}
          <div>
            <h2 className="text-lg font-semibold text-navy-900">Users ({users.length})</h2>
            {users.length === 0 ? (
              <div className="mt-3">
                <EmptyState title="No users" message="No users were returned by the API." />
              </div>
            ) : (
              <div className="mt-3 overflow-x-auto rounded-xl border bg-white shadow-sm">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-slate-50 text-left">
                      <th className="px-4 py-3 font-semibold text-navy-900">Name</th>
                      <th className="px-4 py-3 font-semibold text-navy-900">Email</th>
                      <th className="px-4 py-3 font-semibold text-navy-900">Role</th>
                      <th className="px-4 py-3 font-semibold text-navy-900">Departments</th>
                      <th className="px-4 py-3 font-semibold text-navy-900">Status</th>
                      <th className="px-4 py-3 font-semibold text-navy-900">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => {
                      const isSelf = me?.email === u.email
                      return (
                        <tr key={u.email} className="border-b last:border-0">
                          <td className="px-4 py-3 font-medium text-navy-900">{u.name}</td>
                          <td className="px-4 py-3">{u.email}</td>
                          <td className="px-4 py-3">
                            <select
                              value={u.role}
                              disabled={isSelf || changing}
                              onChange={(e) =>
                                setPendingRole({ user: u, role: e.target.value as Role })
                              }
                              className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200 disabled:opacity-50"
                              aria-label={`Change role for ${u.email}`}
                            >
                              {ROLES.map((r) => (
                                <option key={r} value={r}>
                                  {roleLabel(r)}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td className="px-4 py-3 text-xs text-slate-600">{u.departments.join(', ')}</td>
                          <td className="px-4 py-3">
                            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">
                              Active
                            </span>
                            {isSelf && (
                              <p className="mt-1 text-xs text-slate-500">
                                This is you — your own role cannot be changed.
                              </p>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <button
                              type="button"
                              className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-navy-700 hover:bg-slate-50"
                              onClick={() => {
                                setResetTarget({ email: u.email })
                                setResetPassword('')
                                setResetConfirm('')
                              }}
                            >
                              Reset password
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Password reset requests (v0.10) */}
          <div>
            <h2 className="text-lg font-semibold text-navy-900">
              Password reset requests ({resetRequests.length})
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              Users who forgot their password ask here. There is no email in this system — set a
              new temporary password and give it to them directly. Their old sessions are revoked
              when you reset.
            </p>
            {resetRequests.length === 0 ? (
              <div className="mt-3">
                <EmptyState
                  title="No pending requests"
                  message="No one has asked for a password reset."
                />
              </div>
            ) : (
              <div className="mt-3 overflow-x-auto rounded-xl border bg-white shadow-sm">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-slate-50 text-left">
                      <th className="px-4 py-3 font-semibold text-navy-900">Email</th>
                      <th className="px-4 py-3 font-semibold text-navy-900">Requested</th>
                      <th className="px-4 py-3 font-semibold text-navy-900">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resetRequests.map((r) => (
                      <tr key={r.id} className="border-b last:border-0">
                        <td className="px-4 py-3 font-medium text-navy-900">{r.email}</td>
                        <td className="px-4 py-3 text-slate-600">
                          {new Date(r.requested_at).toLocaleString()}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex gap-2">
                            <button
                              type="button"
                              className="rounded-lg bg-navy-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-navy-800"
                              onClick={() => {
                                setResetTarget({ email: r.email })
                                setResetPassword('')
                                setResetConfirm('')
                              }}
                            >
                              Set new password
                            </button>
                            <button
                              type="button"
                              className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium hover:bg-slate-50"
                              onClick={() => void dismissResetRequest(r.id)}
                            >
                              Dismiss
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Evaluation */}
          <div>
            <h2 className="text-lg font-semibold text-navy-900">Evaluation</h2>
            <div className="mt-3">
              <EvalDashboard />
            </div>
          </div>

          {/* Feedback */}
          <div>
            <h2 className="text-lg font-semibold text-navy-900">Feedback</h2>
            {!feedback || feedback.total === 0 ? (
              <div className="mt-3">
                <EmptyState
                  title="No feedback yet"
                  message="No one has rated an answer yet — use the thumbs up/down buttons on a chat answer."
                />
              </div>
            ) : (
              <div className="mt-3 space-y-3 rounded-xl border bg-white p-5 shadow-sm">
                <p className="text-sm">
                  Total {feedback.total} · 👍 {feedback.up} · 👎 {feedback.down} ·{' '}
                  {feedback.percent_up !== null ? `${feedback.percent_up}% positive` : '—'}
                </p>
                {feedback.worst.length > 0 && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b text-left">
                          <th className="px-2 py-2 font-semibold text-navy-900">Question</th>
                          <th className="px-2 py-2 font-semibold text-navy-900">User</th>
                          <th className="px-2 py-2 font-semibold text-navy-900">Time</th>
                          <th className="px-2 py-2 font-semibold text-navy-900">Comment</th>
                        </tr>
                      </thead>
                      <tbody>
                        {feedback.worst.map((w) => (
                          <tr key={w.message_id} className="border-b last:border-0">
                            <td className="px-2 py-2">{w.question ?? '—'}</td>
                            <td className="px-2 py-2">{w.user_email ?? '—'}</td>
                            <td className="px-2 py-2">{new Date(w.ts).toLocaleString()}</td>
                            <td className="px-2 py-2">{w.comment ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {pendingRole && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label="Confirm role change">
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl">
            <h2 className="text-lg font-semibold text-navy-900">Change this user’s role?</h2>
            <p className="mt-2 text-sm text-slate-600">
              {pendingRole.user.name} ({pendingRole.user.email}) will change from{' '}
              <strong>{roleLabel(pendingRole.user.role)}</strong> to{' '}
              <strong>{roleLabel(pendingRole.role)}</strong>. Their document access changes
              immediately.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPendingRole(null)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={changing}
                onClick={() => void confirmRoleChange()}
                className="rounded-lg bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-50"
              >
                {changing ? 'Changing…' : 'Change role'}
              </button>
            </div>
          </div>
        </div>
      )}
      {resetTarget && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label="Reset password">
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl">
            <h2 className="text-lg font-semibold text-navy-900">Reset password</h2>
            <p className="mt-2 text-sm text-slate-600">
              Set a new temporary password for <strong>{resetTarget.email}</strong>. Their old
              password stops working immediately and all their sessions are revoked. Give them
              the new password directly.
            </p>
            <label className="mt-4 block text-sm font-medium text-slate-700" htmlFor="reset-password">
              New password
            </label>
            <input
              id="reset-password"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
              type="password"
              autoComplete="new-password"
              value={resetPassword}
              onChange={(e) => setResetPassword(e.target.value)}
            />
            <label className="mt-3 block text-sm font-medium text-slate-700" htmlFor="reset-confirm">
              Confirm new password
            </label>
            <input
              id="reset-confirm"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
              type="password"
              autoComplete="new-password"
              value={resetConfirm}
              onChange={(e) => setResetConfirm(e.target.value)}
            />
            <p className="mt-2 text-xs text-slate-500">
              At least 8 characters, with at least one letter and one digit.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setResetTarget(null)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={resetting || !resetPassword}
                onClick={() => void confirmPasswordReset()}
                className="rounded-lg bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-50"
              >
                {resetting ? 'Resetting…' : 'Reset password'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
