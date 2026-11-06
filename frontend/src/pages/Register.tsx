// Sign Up ("/register") — POST /api/v1/auth/register. New accounts
// are always CUSTOMER_SERVICE; a successful register auto-logs in
// exactly like login and redirects to /chat. Backend 400/409 errors
// are shown as-is.
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'

function strengthChecks(password: string) {
  return {
    length: password.length >= 8,
    letterDigit: /[A-Za-z]/.test(password) && /\d/.test(password),
    caseMix: /[a-z]/.test(password) && /[A-Z]/.test(password),
  }
}

export default function Register() {
  const navigate = useNavigate()
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [terms, setTerms] = useState(false)
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const checks = useMemo(() => strengthChecks(password), [password])
  const score = [checks.length, checks.letterDigit, checks.caseMix].filter(Boolean).length
  const strengthLabel = password.length === 0 ? '' : score <= 1 ? 'Weak' : score === 2 ? 'Fair' : 'Strong'
  const strengthBar =
    score === 0
      ? 'w-0'
      : score === 1
        ? 'w-1/3 bg-red-500'
        : score === 2
          ? 'w-2/3 bg-amber-500'
          : 'w-full bg-emerald-500'

  function submit(e: React.FormEvent) {
    e.preventDefault()
    setFieldError(null)
    setError(null)
    if (!fullName.trim()) return setFieldError('Please enter your full name.')
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()))
      return setFieldError('Please enter a valid email address.')
    if (!checks.length || !checks.letterDigit)
      return setFieldError('Password must be at least 8 characters and contain a letter and a digit.')
    if (password !== confirmPassword) return setFieldError('Passwords do not match.')
    if (!terms) return setFieldError('Please accept the terms to create your account.')
    setBusy(true)
    api
      .register(fullName.trim(), email.trim(), password, confirmPassword)
      .then((res) => {
        if (res.data?.user) navigate('/chat')
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Registration failed.')
      })
      .finally(() => setBusy(false))
  }

  const checkRow = (ok: boolean, label: string) => (
    <li className={ok ? 'text-emerald-700' : 'text-slate-500'}>
      {ok ? '✓' : '○'} {label}
    </li>
  )

  return (
    <div className="mx-auto max-w-md px-4 py-10">
      <h1 className="text-2xl font-bold text-navy-900">Create your account</h1>
      <p className="mt-1 text-sm text-slate-600">
        New accounts start as <strong>Customer Service</strong> — an Admin can grant more access later.
      </p>

      <form onSubmit={submit} className="mt-6 rounded-xl border bg-white p-6 shadow-sm" noValidate>
        <label className="block text-sm font-medium text-slate-700" htmlFor="reg-name">
          Full name
        </label>
        <input
          id="reg-name"
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
          type="text"
          autoComplete="name"
          required
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
        />

        <label className="mt-4 block text-sm font-medium text-slate-700" htmlFor="reg-email">
          Email
        </label>
        <input
          id="reg-email"
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />

        <label className="mt-4 block text-sm font-medium text-slate-700" htmlFor="reg-password">
          Password
        </label>
        <input
          id="reg-password"
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
          type="password"
          autoComplete="new-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {password.length > 0 && (
          <div className="mt-2">
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
              <div className={`h-full rounded-full transition-all ${strengthBar}`} />
            </div>
            <div className="mt-1 flex items-center justify-between text-xs">
              <span className="font-medium text-slate-700">Strength: {strengthLabel}</span>
            </div>
            <ul className="mt-1 space-y-0.5 text-xs">
              {checkRow(checks.length, 'At least 8 characters')}
              {checkRow(checks.letterDigit, 'Contains a letter and a digit')}
              {checkRow(checks.caseMix, 'Mix of upper- and lower-case letters')}
            </ul>
          </div>
        )}

        <label className="mt-4 block text-sm font-medium text-slate-700" htmlFor="reg-confirm">
          Confirm password
        </label>
        <input
          id="reg-confirm"
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
          type="password"
          autoComplete="new-password"
          required
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
        />
        {confirmPassword.length > 0 && password !== confirmPassword && (
          <p className="mt-1 text-xs text-red-600">Passwords do not match.</p>
        )}

        <label className="mt-4 flex items-start gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={terms}
            onChange={(e) => setTerms(e.target.checked)}
            className="mt-0.5 h-4 w-4 accent-navy-900"
          />
          <span>
            I understand this is a bank system: I will only use documents my role is allowed to see,
            and my questions and logins are recorded in the audit trail.
          </span>
        </label>

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
          {busy ? 'Creating account…' : 'Create account'}
        </button>
        <p className="mt-3 text-center text-sm text-slate-600">
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-navy-700 hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </div>
  )
}
