// Sign In ("/login") — real POST /api/v1/auth/login. Backend 401
// messages are shown as-is. Demo accounts: one click fills the form
// AND signs in. "Forgot password?" (v0.10) opens the real request
// form: the request is recorded for the admin, who sets a new
// temporary password (there is no email in this system, so nothing
// is emailed — the admin hands the new password to the user).
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, DEMO_ACCOUNTS } from '../api/client'

const REMEMBER_KEY = 'rtb_remembered_email'

export default function Login() {
  const navigate = useNavigate()
  const [email, setEmail] = useState(() => localStorage.getItem(REMEMBER_KEY) ?? '')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [rememberMe, setRememberMe] = useState(() => localStorage.getItem(REMEMBER_KEY) !== null)
  const [error, setError] = useState<string | null>(null)
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [forgotOpen, setForgotOpen] = useState(false)
  const [forgotEmail, setForgotEmail] = useState('')
  const [forgotBusy, setForgotBusy] = useState(false)
  const [forgotMessage, setForgotMessage] = useState<string | null>(null)
  const [forgotError, setForgotError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Production (v0.8): demo accounts are OFF in production
  // (RTB_DEMO_ACCOUNTS=0) — the backend reports it on /health, and
  // this page hides the demo section then. If /health cannot be
  // reached the section stays visible (dev default).
  const [demoVisible, setDemoVisible] = useState(true)
  useEffect(() => {
    let cancelled = false
    api
      .health()
      .then((res) => {
        if (!cancelled && res.data?.demo_accounts_enabled === false) setDemoVisible(false)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  async function doLogin(em: string, pw: string) {
    setError(null)
    setFieldError(null)
    setBusy(true)
    try {
      const res = await api.login(em, pw)
      if (res.data?.user) {
        if (rememberMe) localStorage.setItem(REMEMBER_KEY, em)
        else localStorage.removeItem(REMEMBER_KEY)
        navigate('/chat')
      }
    } catch (err) {
      // 401 from the backend: "Invalid email or password." — shown as-is.
      setError(err instanceof Error ? err.message : 'Login failed.')
    } finally {
      setBusy(false)
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim() || !password) {
      setFieldError('Please enter your email and password.')
      return
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setFieldError('Please enter a valid email address.')
      return
    }
    void doLogin(email.trim(), password)
  }

  return (
    <div className="mx-auto max-w-md px-4 py-10">
      <h1 className="text-2xl font-bold text-navy-900">Sign in</h1>
      <p className="mt-1 text-sm text-slate-600">
        Sign in to ask the bank’s knowledge base. Your role decides which documents you can see.
      </p>

      <form onSubmit={submit} className="mt-6 rounded-xl border bg-white p-6 shadow-sm" noValidate>
        <label className="block text-sm font-medium text-slate-700" htmlFor="login-email">
          Email
        </label>
        <input
          id="login-email"
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label className="mt-4 block text-sm font-medium text-slate-700" htmlFor="login-password">
          Password
        </label>
        <div className="relative mt-1">
          <input
            id="login-password"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 pr-16 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
            type={showPassword ? 'text' : 'password'}
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button
            type="button"
            className="absolute right-2 top-1/2 -translate-y-1/2 text-xs font-medium text-navy-700 hover:underline"
            onClick={() => setShowPassword((v) => !v)}
            aria-label={showPassword ? 'Hide password' : 'Show password'}
          >
            {showPassword ? 'Hide' : 'Show'}
          </button>
        </div>

        <div className="mt-4 flex items-center justify-between text-sm">
          <label className="flex items-center gap-2 text-slate-700">
            <input
              type="checkbox"
              checked={rememberMe}
              onChange={(e) => setRememberMe(e.target.checked)}
              className="h-4 w-4 accent-navy-900"
            />
            Remember me
          </label>
          <button
            type="button"
            className="font-medium text-navy-700 hover:underline"
            onClick={() => {
              setForgotOpen((v) => !v)
              setForgotEmail(email)
              setForgotMessage(null)
              setForgotError(null)
            }}
          >
            Forgot password?
          </button>
        </div>
        {forgotOpen && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-3" role="status">
            <p className="text-sm text-amber-800">
              Enter your email and the admin will set a new temporary password for you. There is
              no email in this system — the admin will give you the new password directly.
            </p>
            <form
              className="mt-2 flex gap-2"
              onSubmit={async (e) => {
                e.preventDefault()
                if (!forgotEmail.trim()) {
                  setForgotError('Please enter your email address.')
                  return
                }
                setForgotBusy(true)
                setForgotError(null)
                setForgotMessage(null)
                try {
                  const res = await api.forgotPassword(forgotEmail.trim())
                  setForgotMessage(res.data?.message ?? 'Your request has been recorded.')
                } catch (err) {
                  setForgotError(err instanceof Error ? err.message : 'Request failed.')
                } finally {
                  setForgotBusy(false)
                }
              }}
            >
              <input
                className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
                type="email"
                placeholder="you@rtb.local"
                autoComplete="email"
                value={forgotEmail}
                onChange={(e) => setForgotEmail(e.target.value)}
              />
              <button
                type="submit"
                disabled={forgotBusy}
                className="shrink-0 rounded-lg bg-navy-900 px-3 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-50"
              >
                {forgotBusy ? 'Sending…' : 'Request reset'}
              </button>
            </form>
            {forgotMessage && <p className="mt-2 text-sm text-green-700">{forgotMessage}</p>}
            {forgotError && <p className="mt-2 text-sm text-red-600">{forgotError}</p>}
          </div>
        )}

        {fieldError && <p className="mt-3 text-sm text-red-600">{fieldError}</p>}
        {error && (
          <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="dark-btn mt-5 w-full rounded-lg bg-navy-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-50"
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="mt-3 text-center text-sm text-slate-600">
          No account yet?{' '}
          <Link to="/register" className="font-medium text-navy-700 hover:underline">
            Create one
          </Link>
        </p>
      </form>

      {demoVisible && (
        <div className="mt-4 rounded-xl border bg-white p-6 shadow-sm">
          <p className="text-sm font-semibold text-navy-900">Demo accounts — demo only</p>
        <p className="mt-1 text-xs text-slate-500">
          Click one to sign in instantly. Change these passwords before any real use.
        </p>
        <ul className="mt-3 space-y-2">
          {DEMO_ACCOUNTS.map((acc) => (
            <li key={acc.email}>
              <button
                type="button"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-left text-sm hover:bg-slate-50 disabled:opacity-50"
                disabled={busy}
                onClick={() => void doLogin(acc.email, acc.password)}
              >
                <span className="font-medium text-navy-900">{acc.label}</span>
                <br />
                <span className="text-slate-500">{acc.email}</span>
              </button>
            </li>
          ))}
        </ul>
        </div>
      )}
    </div>
  )
}
