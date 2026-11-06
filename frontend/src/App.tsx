// App shell (v0.7) — public landing + auth pages, then a sidebar
// layout for signed-in users. Guards: unauthenticated users are sent
// to /login; non-admins visiting /admin, /audit or /evaluation get a
// clear "Admin only" page (the backend enforces it too — hiding the
// links is not the enforcement).
import { useEffect, useState, type ReactNode } from 'react'
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { api, getStoredUser, logout, roleLabel, type HealthResponse, type User } from './api/client'
import { ToastProvider } from './components/Toast'
import EvalDashboard from './components/EvalDashboard'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Register from './pages/Register'
import Chat from './pages/Chat'
import Documents from './pages/Documents'
import AuditLog from './pages/AuditLog'
import Admin from './pages/Admin'
import Monitoring from './pages/Monitoring'

type ApiState = 'checking' | 'online' | 'offline'

function AdminOnly() {
  return (
    <section className="mx-auto max-w-md rounded-xl border border-amber-300 bg-amber-50 p-6 text-center shadow-sm">
      <h1 className="text-xl font-bold text-amber-900">Admin only</h1>
      <p className="mt-2 text-sm text-amber-800">
        This page is only available to Admin users. Your role does not have access — if you need
        it, ask an Admin to change your role.
      </p>
      <Link
        to="/chat"
        className="mt-4 inline-block rounded-lg bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-800"
      >
        Back to chat
      </Link>
    </section>
  )
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const user = getStoredUser()
  if (!user) return <Navigate to="/login" replace />
  if (user.role !== 'ADMIN') return <AdminOnly />
  return <>{children}</>
}

const NAV = [
  { to: '/chat', label: 'Chat', admin: false },
  { to: '/documents', label: 'Documents', admin: false },
  { to: '/audit', label: 'Audit Log', admin: true },
  { to: '/evaluation', label: 'Evaluation', admin: true },
  { to: '/monitoring', label: 'Monitoring', admin: true },
  { to: '/admin', label: 'Admin', admin: true },
]

function Shell({ user, apiState, health, onLogout }: {
  user: User
  apiState: ApiState
  health: HealthResponse | null
  onLogout: () => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()
  const isAdmin = user.role === 'ADMIN'
  const visibleNav = NAV.filter((n) => !n.admin || isAdmin)

  const linkCls = ({ isActive }: { isActive: boolean }) =>
    `block rounded-lg px-3 py-2 text-sm font-medium ${
      isActive ? 'bg-navy-900 text-white' : 'text-slate-700 hover:bg-slate-100'
    }`

  const badge =
    apiState === 'online'
      ? 'bg-emerald-100 text-emerald-800'
      : apiState === 'offline'
        ? 'bg-red-100 text-red-800'
        : 'bg-amber-100 text-amber-800'
  const label =
    apiState === 'online'
      ? `API online — v${health?.data.version ?? '?'}`
      : apiState === 'offline'
        ? 'API offline'
        : 'Checking API…'

  return (
    <div className="flex min-h-screen">
      {/* Sidebar (desktop) */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-white px-4 py-5 md:flex">
        <Link to="/chat" className="px-1">
          <p className="text-base font-bold leading-tight text-navy-900">Riyadh Trust Bank</p>
          <p className="text-xs text-slate-500">Enterprise Intelligence Platform</p>
        </Link>
        <nav className="mt-6 flex flex-col gap-1">
          {visibleNav.map((n) => (
            <NavLink key={n.to} to={n.to} className={linkCls}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto pt-6">
          <p className="px-1 text-sm font-medium text-navy-900">{user.name}</p>
          <p className="px-1 text-xs text-slate-500">{user.email}</p>
          <span className="mt-2 inline-block rounded-full bg-navy-100 px-2 py-0.5 text-xs font-medium text-navy-800">
            {roleLabel(user.role)}
          </span>
          <button
            type="button"
            onClick={onLogout}
            className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-navy-900 hover:bg-slate-50"
          >
            Log out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Topbar */}
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm md:hidden"
              onClick={() => setMenuOpen((v) => !v)}
              aria-label="Toggle navigation menu"
            >
              ☰
            </button>
            <Link to="/chat" className="text-sm font-bold text-navy-900 md:hidden">
              Riyadh Trust Bank
            </Link>
            <span className="hidden text-sm text-slate-500 sm:block">
              {location.pathname === '/chat' && 'Chat'}
              {location.pathname === '/documents' && 'Documents'}
              {location.pathname === '/audit' && 'Audit Log'}
              {location.pathname === '/evaluation' && 'Evaluation'}
              {location.pathname === '/monitoring' && 'Monitoring'}
              {location.pathname === '/admin' && 'Admin'}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className={`hidden rounded-full px-2 py-1 text-xs font-medium sm:inline-block ${badge}`}>
              {label}
            </span>
            <span className="text-sm text-slate-700">
              {user.name} · <span className="font-medium text-navy-900">{roleLabel(user.role)}</span>
            </span>
            <button
              type="button"
              onClick={onLogout}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-navy-900 hover:bg-slate-50 md:hidden"
            >
              Log out
            </button>
          </div>
        </header>

        {/* Mobile nav */}
        {menuOpen && (
          <nav className="flex flex-col gap-1 border-b border-slate-200 bg-white px-4 py-3 md:hidden">
            {visibleNav.map((n) => (
              <NavLink key={n.to} to={n.to} className={linkCls} onClick={() => setMenuOpen(false)}>
                {n.label}
              </NavLink>
            ))}
          </nav>
        )}

        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6 sm:px-6">
          <Routes>
            <Route path="/chat" element={<Chat />} />
            <Route path="/documents" element={<Documents />} />
            <Route
              path="/audit"
              element={
                <RequireAdmin>
                  <AuditLog />
                </RequireAdmin>
              }
            />
            <Route
              path="/evaluation"
              element={
                <RequireAdmin>
                  <section>
                    <h1 className="text-2xl font-bold text-navy-900">Evaluation</h1>
                    <div className="mt-4">
                      <EvalDashboard />
                    </div>
                  </section>
                </RequireAdmin>
              }
            />
            <Route
              path="/monitoring"
              element={
                <RequireAdmin>
                  <Monitoring />
                </RequireAdmin>
              }
            />
            <Route
              path="/admin"
              element={
                <RequireAdmin>
                  <Admin />
                </RequireAdmin>
              }
            />
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}

export default function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const [apiState, setApiState] = useState<ApiState>('checking')
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [user, setUser] = useState<User | null>(() => getStoredUser())

  // Refresh the shell user whenever the route changes (e.g. after a
  // successful login navigates to /chat).
  useEffect(() => {
    setUser(getStoredUser())
  }, [location.pathname])

  async function onLogout() {
    await logout()
    setUser(null)
    navigate('/login')
  }

  useEffect(() => {
    let cancelled = false
    api
      .health()
      .then((h) => {
        if (!cancelled) {
          setHealth(h)
          setApiState(h.data.status === 'ok' ? 'online' : 'offline')
        }
      })
      .catch(() => {
        if (!cancelled) setApiState('offline')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const isPublicRoute =
    location.pathname === '/' || location.pathname === '/login' || location.pathname === '/register'

  // Read the stored session synchronously on every render: after a
  // successful login the route changes to /chat BEFORE the effect
  // below has run, so relying on `user` state alone made App render
  // <Navigate to="/login"> and bounce the user straight back to the
  // sign-in page (found by live browser testing, v0.7). The effect
  // still syncs state for logout / role changes.
  const currentUser = user ?? getStoredUser()

  return (
    <ToastProvider>
      {isPublicRoute ? (
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      ) : currentUser ? (
        <Shell user={currentUser} apiState={apiState} health={health} onLogout={onLogout} />
      ) : (
        <Navigate to="/login" replace />
      )}
    </ToastProvider>
  )
}
