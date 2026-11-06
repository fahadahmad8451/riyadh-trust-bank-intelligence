// Public landing page ("/") — the product's front door. Logged-in
// users are sent straight to /chat. All numbers are real, from the
// indexed knowledge base: 8 documents, 15 chunks, 3 roles, 24 pages.
import { Link, Navigate } from 'react-router-dom'
import { getStoredUser } from '../api/client'

const FEATURES = [
  {
    title: 'Grounded answers with citations',
    body: 'Every answer comes only from the bank’s own indexed documents — KYC, AML, SAMA compliance, loans, HR and more — and shows exactly which document and page it came from.',
  },
  {
    title: 'Role-based access (RBAC)',
    body: 'Access is enforced in the backend before any document is retrieved. A Customer Service user never sees Compliance or HR documents — not even in a citation.',
  },
  {
    title: 'Full audit trail',
    body: 'Every login, question, upload and denied access is logged with user, role, time and result. Admins can review the complete trail at any time.',
  },
  {
    title: 'Arabic + English',
    body: 'Ask in English or العربية. Answers are grounded in the same documents either way, with citations you can check.',
  },
]

const STEPS = [
  {
    n: '1',
    title: 'Sign in with your bank role',
    body: 'Your account carries one of three roles — Customer Service, Compliance Officer or Admin — and that role decides what you can see.',
  },
  {
    n: '2',
    title: 'Ask a question',
    body: 'Type a question about a policy, a procedure or a regulation. The system retrieves the relevant sections from the indexed documents.',
  },
  {
    n: '3',
    title: 'Get a cited answer',
    body: 'You get an answer built only from those sections, with a citation card for every source — document, page and relevance score.',
  },
]

const ROLES = [
  {
    name: 'Customer Service',
    sees: 'Retail documents',
    detail: 'KYC Policy, Account Opening Policy, Personal Loan Policy, Charges & Fees Schedule — 4 documents.',
  },
  {
    name: 'Compliance Officer',
    sees: 'Retail + Compliance documents',
    detail: 'Everything Customer Service sees, plus AML Policy and the SAMA Compliance Summary — 6 documents.',
  },
  {
    name: 'Admin — Branch Manager',
    sees: 'All documents',
    detail: 'Everything above, plus HR Leave Policy and the PDPL Data Privacy Summary — all 8 documents, plus user management and uploads.',
  },
]

const STATS = [
  { value: '8', label: 'Indexed documents' },
  { value: '15', label: 'Searchable sections (chunks)' },
  { value: '24', label: 'Document pages' },
  { value: '3', label: 'Access roles' },
]

export default function Landing() {
  if (getStoredUser()) return <Navigate to="/chat" replace />

  return (
    <div className="bg-white">
      {/* Hero — plain-CSS .hero-bg is the fallback if a Tailwind colour
          class is ever missing/stale (landing-fix v0.9.1). */}
      <section className="hero-bg bg-navy-900 text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 sm:py-20">
          <p className="hero-kicker text-sm font-semibold uppercase tracking-widest text-gold-400">
            Riyadh Trust Bank — Enterprise Intelligence Platform
          </p>
          <h1 className="mt-4 max-w-2xl text-4xl font-bold leading-tight sm:text-5xl">
            Bank knowledge, answered with proof.
          </h1>
          <p className="hero-sub mt-4 max-w-2xl text-lg text-slate-300">
            Ask a question about bank policy and get an answer grounded in the bank’s own documents —
            with a citation for every claim, and access controlled by your role.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              to="/login"
              className="hero-gold-btn rounded-lg bg-gold-500 px-6 py-3 text-sm font-semibold text-navy-950 hover:bg-gold-400"
            >
              Sign in
            </Link>
            <Link
              to="/register"
              className="hero-outline-btn rounded-lg border border-white/40 px-6 py-3 text-sm font-semibold text-white hover:bg-white/10"
            >
              Create an account
            </Link>
          </div>
          <dl className="mt-12 grid grid-cols-2 gap-6 sm:grid-cols-4">
            {STATS.map((s) => (
              <div key={s.label} className="border-l-2 border-gold-500 pl-4">
                <dt className="sr-only">{s.label}</dt>
                <dd className="hero-stat-value text-3xl font-bold text-white">{s.value}</dd>
                <dd className="hero-stat-label mt-1 text-sm text-slate-300">{s.label}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-10 text-xs text-slate-400">Build v0.10.1</p>
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-6xl px-6 py-14">
        <h2 className="text-2xl font-bold text-navy-900">What the platform does</h2>
        <div className="mt-6 grid gap-5 sm:grid-cols-2">
          {FEATURES.map((f) => (
            <article key={f.title} className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="text-lg font-semibold text-navy-900">{f.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{f.body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="bg-slate-50">
        <div className="mx-auto max-w-6xl px-6 py-14">
          <h2 className="text-2xl font-bold text-navy-900">How it works</h2>
          <div className="mt-6 grid gap-5 md:grid-cols-3">
            {STEPS.map((s) => (
              <article key={s.n} className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
                <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-navy-900 text-sm font-bold text-white">
                  {s.n}
                </span>
                <h3 className="mt-3 text-lg font-semibold text-navy-900">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-600">{s.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* Roles */}
      <section className="mx-auto max-w-6xl px-6 py-14">
        <h2 className="text-2xl font-bold text-navy-900">Who can see what</h2>
        <p className="mt-2 text-sm text-slate-600">
          Access is decided by your role, enforced by the backend — not by hiding buttons.
        </p>
        <div className="mt-6 grid gap-5 md:grid-cols-3">
          {ROLES.map((r) => (
            <article key={r.name} className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="text-lg font-semibold text-navy-900">{r.name}</h3>
              <p className="mt-1 text-sm font-medium text-teal-700">{r.sees}</p>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{r.detail}</p>
            </article>
          ))}
        </div>
      </section>

      {/* Footer — plain-CSS .footer-bg is the fallback (landing-fix v0.9.1). */}
      <footer className="footer-bg border-t border-slate-200 bg-navy-950 text-slate-300">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-6 py-8 text-sm sm:flex-row sm:items-center sm:justify-between">
          <p className="footer-title font-semibold text-white">Riyadh Trust Bank — Enterprise Intelligence Platform</p>
          <p>
            Demo deployment — synthetic documents only, no real customer data. Tokens are stored in
            the browser (demo setup).
          </p>
          <p className="text-xs text-slate-400">v0.10.1</p>
        </div>
      </footer>
    </div>
  )
}
