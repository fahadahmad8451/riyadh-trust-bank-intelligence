// Real API client — talks to FastAPI at /api/v1 (proxied by Vite in dev).
// v0.10: httpOnly cookie auth. The access + refresh tokens live in
// HttpOnly cookies set by the backend — JavaScript NEVER sees them,
// so nothing token-like is stored in localStorage (only the user's
// display info, for the sidebar/topbar). Every fetch sends
// credentials: 'include' so the browser attaches the cookies, and
// the 401 path retries once via POST /auth/refresh (cookie-based).
// No fake data: every function performs a real fetch and surfaces errors.
//
// v0.10.2 — same-host API base (fixes the login bounce).
// Root cause: the staging/production builds baked in
// VITE_API_URL=http://127.0.0.1:<api-port>, while the user opens the
// page at http://localhost:<web-port>. That is cross-site, so the
// browser does NOT send SameSite=Lax httpOnly cookies on fetch POSTs:
// login returned 200 (the Set-Cookie header arrived), but the next
// /chat and /auth/refresh calls went out WITHOUT cookies -> 401 ->
// the app bounced back to the login page. API clients (curl/pytest)
// never showed this — SameSite only applies in a real browser.
// Fix: when VITE_API_URL is set, keep its protocol, port and path
// (the override still decides WHERE the API listens), but swap its
// hostname for window.location.hostname — the host the page was
// actually opened on. So the API is always same-site, whether the
// user opens localhost or 127.0.0.1, and the cookies are sent.
// When VITE_API_URL is empty (dev), calls stay relative (/api/...)
// and go through the Vite dev proxy as before. Fail-open: if the
// env value cannot be parsed as a URL, use it unchanged.
function resolveApiBase(): string {
  const raw = ((import.meta.env.VITE_API_URL as string | undefined) ?? '').trim().replace(/\/$/, '')
  if (!raw) return ''
  if (!/^https?:\/\//i.test(raw)) return raw
  try {
    const u = new URL(raw)
    u.hostname = window.location.hostname
    return u.toString().replace(/\/$/, '')
  } catch {
    return raw
  }
}
const API_BASE = resolveApiBase()
function url(path: string): string {
  return `${API_BASE}${path}`
}

export interface HealthResponse {
  success: boolean
  data: {
    status: string
    service: string
    version: string
    environment: string
    // Production (v0.8) extended health — all optional so older
    // backends still type-check.
    uptime_seconds?: number
    demo_accounts_enabled?: boolean
    reranker?: string
    embeddings?: { model: string | null; dim: number | null; backend: string | null }
    vector_store?: { status: string; documents: number | null; chunks: number | null }
    generation_mode?: string
    database?: string
  }
  error: string | null
  request_id: string
}

export interface MetricsResponse {
  success: boolean
  data: {
    uptime_seconds: number
    version: string
    environment: string
    endpoints_implemented: string[]
    endpoints_pending: string[]
  }
  error: string | null
  request_id: string
}

export interface Citation {
  document_id: string
  document_title: string
  page_no: number | null
  department: string
  score: number | null
}

export interface EvalQuestionResult {
  id: string
  question: string
  language: string
  expected_documents: string[]
  top_document: string | null
  top_doc_correct: boolean
  context_recall: number
  faithfulness: number
  answer_relevancy: number
  phrase_present: boolean
  refused: boolean
  generation_mode: string
  latency_ms: number
}

export interface EvalReport {
  method: string
  ragas_used: boolean
  ragas_note: string
  targets: Record<string, number>
  question_count: number
  aggregates: {
    faithfulness: number
    context_recall: number
    answer_relevancy: number
    top_doc_accuracy: number
    phrase_present_rate: number
    refused_count: number
    latency_ms_p50: number
    latency_ms_p95: number
  }
  verdict_vs_targets: Record<string, boolean>
  all_targets_met: boolean
  run_seconds: number
  run_at: string
  questions: EvalQuestionResult[]
}

export interface FeedbackStats {
  total: number
  up: number
  down: number
  percent_up: number | null
  worst: Array<{
    message_id: string
    user_email: string | null
    comment: string | null
    ts: string
    question: string | null
    answer_excerpt: string
    citations: Citation[]
  }>
}

export interface MonitoringSummary {
  total_requests: number
  requests_by_endpoint: Record<string, number>
  requests_by_status: Record<string, string>
  errors_5xx: number
  errors_4xx: number
  error_rate_5xx: number
  latency_ms_p50: number | null
  latency_ms_p95: number | null
  chat_latency_ms_p50: number | null
  chat_latency_ms_p95: number | null
  chats_total: number
  rbac_refusals_total: number
  failed_logins_total: number
  feedback_total: number
  feedback_up: number
  feedback_down: number
  uptime_seconds: number
}

export interface TimeseriesBucket {
  hour: string
  requests: number
  errors_5xx: number
  chats: number
  p95_ms: number | null
}

export interface AlertRow {
  id: string
  ts: string
  rule: string
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM'
  message: string
  status: 'active' | 'acknowledged'
  context: Record<string, unknown>
  acknowledged_by: string | null
  acknowledged_at: string | null
}

export interface MonitoringOverview {
  health: HealthResponse['data']
  summary: MonitoringSummary
  disk: { total_gb: number; used_gb: number; free_gb: number; used_percent: number | null }
  data_dir_mb: number | null
  alerts_active: number
  alerts_critical_active: number
  alerts_high_active: number
  alerts_total: number
  recent_errors: Array<{
    ts: string
    endpoint: string
    method: string
    status: number
    latency_ms: number
    role: string | null
  }>
}

export interface ChatResponse {
  success: boolean
  data: {
    conversation_id: string
    message_id: string
    answer: string
    citations: Citation[]
    retrieval_scores: Record<string, unknown>
    latency_ms: number
    generation_mode: string
    language: string
    retrieved_count: number
    refused: boolean
    rbac_enforced: boolean
    role?: string
    allowed_departments?: string[]
  }
  error: string | null
  request_id: string
}

export interface User {
  email: string
  name: string
  role: string
  departments: string[]
}

export interface DocumentRow {
  document_id: string
  title: string
  department: string
  type: string
  version: string
  chunk_count: number
}

export interface AuditRow {
  ts: string
  user: string | null
  role: string | null
  action: string
  resource: string | null
  result: string
  detail: string | null
  ip?: string | null
}

export const ROLES = ['ADMIN', 'COMPLIANCE_OFFICER', 'CUSTOMER_SERVICE'] as const
export type Role = (typeof ROLES)[number]

export function roleLabel(role: string): string {
  switch (role) {
    case 'ADMIN':
      return 'Admin — Branch Manager'
    case 'COMPLIANCE_OFFICER':
      return 'Compliance Officer'
    case 'CUSTOMER_SERVICE':
      return 'Customer Service'
    default:
      return role
  }
}

// Which roles can see a document of a given department (SPRINT3 RBAC map).
export function rolesForDepartment(department: string): string[] {
  switch (department) {
    case 'RETAIL':
      return ['CUSTOMER_SERVICE', 'COMPLIANCE_OFFICER', 'ADMIN']
    case 'COMPLIANCE':
      return ['COMPLIANCE_OFFICER', 'ADMIN']
    case 'HR':
      return ['ADMIN']
    default:
      return ['ADMIN']
  }
}

export interface LoginResponse {
  success: boolean
  data: {
    // v0.10: no tokens in the body — they arrive as httpOnly cookies.
    token_type: string
    expires_in_minutes: number
    user: User
  } | null
  error: string | null
  request_id: string
}

// v0.10: only the user's display info is stored locally (for the
// sidebar/topbar). Tokens live in httpOnly cookies and are never
// readable or writable from JavaScript.
const USER_KEY = 'rtb_user'

export function getStoredUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

export function isLoggedIn(): boolean {
  return getStoredUser() !== null
}

export function storeUser(user: User | null | undefined): void {
  if (!user) return
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearStoredUser(): void {
  localStorage.removeItem(USER_KEY)
}

export async function logout(): Promise<void> {
  try {
    await fetch(url('/api/v1/auth/logout'), {
      method: 'POST',
      credentials: 'include',
    })
  } catch {
    // Backend unreachable — still clear local session below.
  }
  clearStoredUser()
}

// The API envelope carries a plain-English `error` string — surface
// that instead of the raw JSON body when a call fails.
function extractApiError(status: number, text: string): string {
  try {
    const body = JSON.parse(text) as { error?: unknown }
    if (typeof body.error === 'string' && body.error) return body.error
  } catch {
    // Not JSON — fall through to the raw text.
  }
  return text ? `API ${status}: ${text}` : `API ${status}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  }
  // v0.10: cookies carry the session (credentials: 'include'); no
  // Authorization header is ever set from JavaScript.
  const res = await fetch(url(path), { ...init, headers, credentials: 'include' })
  if (res.status === 401) {
    // Token expired/invalid — try one refresh, then give up.
    const refreshed = await tryRefresh()
    if (refreshed) {
      const retry = await fetch(url(path), { ...init, headers, credentials: 'include' })
      if (!retry.ok) throw new Error(extractApiError(retry.status, await retry.text()))
      return (await retry.json()) as T
    }
    throw new Error('UNAUTHORIZED')
  }
  if (!res.ok) {
    throw new Error(extractApiError(res.status, await res.text()))
  }
  return (await res.json()) as T
}

async function tryRefresh(): Promise<boolean> {
  // v0.10: the refresh token travels in its httpOnly cookie — no
  // body is needed. On success the response carries the user; store
  // it so the shell (name/role) stays in sync.
  try {
    const res = await fetch(url('/api/v1/auth/refresh'), {
      method: 'POST',
      credentials: 'include',
    })
    if (!res.ok) return false
    const body = (await res.json()) as LoginResponse
    storeUser(body.data?.user)
    return true
  } catch {
    return false
  }
}

export interface DemoAccount {
  email: string
  password: string
  label: string
}

export const DEMO_ACCOUNTS: DemoAccount[] = [
  { email: 'admin@rtb.local', password: 'Admin123!', label: 'Admin — Branch Manager (full access)' },
  { email: 'compliance@rtb.local', password: 'Compliance123!', label: 'Compliance Officer (Retail + Compliance)' },
  { email: 'service@rtb.local', password: 'Service123!', label: 'Customer Service (Retail only)' },
]

export interface PasswordResetRequestRow {
  id: string
  email: string
  status: 'pending' | 'resolved' | 'dismissed'
  requested_at: string
  resolved_by: string | null
  resolved_at: string | null
}

export const api = {
  health: () => request<HealthResponse>('/api/v1/health'),
  metrics: () => request<MetricsResponse>('/api/v1/metrics'),
  login: async (email: string, password: string): Promise<LoginResponse> => {
    const res = await fetch(url('/api/v1/auth/login'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, password }),
    })
    const body = (await res.json()) as LoginResponse
    if (!res.ok) throw new Error(body.error ?? `Login failed (${res.status})`)
    storeUser(body.data?.user)
    return body
  },
  me: () => request<{ success: boolean; data: { user: User } }>('/api/v1/auth/me'),
  // v0.7: sign-up. New accounts are always CUSTOMER_SERVICE; a
  // successful register auto-logs in exactly like login does.
  register: async (
    fullName: string,
    email: string,
    password: string,
    confirmPassword: string,
  ): Promise<LoginResponse> => {
    const res = await fetch(url('/api/v1/auth/register'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        full_name: fullName,
        email,
        password,
        confirm_password: confirmPassword,
      }),
    })
    const body = (await res.json()) as LoginResponse
    if (!res.ok) throw new Error(body.error ?? `Registration failed (${res.status})`)
    storeUser(body.data?.user)
    return body
  },
  chat: async (question: string, conversationId?: string): Promise<ChatResponse> => {
    return request<ChatResponse>('/api/v1/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, conversation_id: conversationId ?? null }),
    })
  },
  documents: () =>
    request<{ success: boolean; data: { documents: DocumentRow[]; count: number; role: string } }>(
      '/api/v1/documents',
    ),
  document: (id: string) =>
    request<{ success: boolean; data: { document: DocumentRow } }>(
      `/api/v1/documents/${encodeURIComponent(id)}`,
    ),
  // v0.7: ADMIN-only document upload (multipart) and delete.
  uploadDocument: (file: File, title?: string, department?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (title) form.append('title', title)
    if (department) form.append('department', department)
    return request<{ success: boolean; data: { document: DocumentRow } }>('/api/v1/documents/upload', {
      method: 'POST',
      body: form,
    })
  },
  deleteDocument: (id: string) =>
    request<{ success: boolean; data: { message: string } }>(
      `/api/v1/documents/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    ),
  feedback: (messageId: string, rating: 'up' | 'down', comment?: string) =>
    request<{ success: boolean; data: { message: string; updated: boolean } }>('/api/v1/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_id: messageId, rating, comment: comment ?? null }),
    }),
  feedbackStats: () =>
    request<{ success: boolean; data: FeedbackStats }>('/api/v1/admin/feedback-stats'),
  evalResults: () =>
    request<{ success: boolean; data: EvalReport; error: string | null }>('/api/v1/eval/results'),
  evalRun: (limit?: number) =>
    request<{ success: boolean; data: EvalReport }>(
      limit ? `/api/v1/eval/run?limit=${limit}` : '/api/v1/eval/run',
    ),
  // v0.10: password reset (no email exists, so the flow is a
  // request the admin approves by setting a new temporary password).
  forgotPassword: (email: string) =>
    request<{ success: boolean; data: { message: string } }>('/api/v1/auth/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    }),
  passwordResetRequests: (status?: string) =>
    request<{ success: boolean; data: { requests: PasswordResetRequestRow[]; count: number } }>(
      status ? `/api/v1/admin/password-reset-requests?status=${status}` : '/api/v1/admin/password-reset-requests',
    ),
  resetUserPassword: (email: string, newPassword: string, confirmPassword: string) =>
    request<{ success: boolean; data: { user: User } }>(
      `/api/v1/admin/users/${encodeURIComponent(email)}/reset-password`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: newPassword, confirm_password: confirmPassword }),
      },
    ),
  dismissPasswordResetRequest: (id: string) =>
    request<{ success: boolean; data: { request: PasswordResetRequestRow } }>(
      `/api/v1/admin/password-reset-requests/${encodeURIComponent(id)}/dismiss`,
      { method: 'POST' },
    ),
  adminUsers: () =>
    request<{ success: boolean; data: { users: User[]; count: number } }>('/api/v1/admin/users'),
  // v0.7: change a user's role (ADMIN only; the backend refuses
  // changing your own role with a 400).
  changeUserRole: (email: string, role: Role) =>
    request<{ success: boolean; data: { user: User } }>(
      `/api/v1/admin/users/${encodeURIComponent(email)}/role`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
      },
    ),
  auditLogs: (limit = 100, offset = 0) =>
    request<{
      success: boolean
      data: { audit_logs: AuditRow[]; count: number; total: number }
    }>(`/api/v1/admin/audit-logs?limit=${limit}&offset=${offset}`),
  // v0.9: Monitoring (ADMIN only). All data is real — recorded
  // request metrics, the audit log and the alerts file.
  monitoringOverview: () =>
    request<{ success: boolean; data: MonitoringOverview }>('/api/v1/admin/monitoring/overview'),
  monitoringSummary: () =>
    request<{ success: boolean; data: MonitoringSummary }>('/api/v1/admin/metrics'),
  monitoringTimeseries: (hours = 24) =>
    request<{ success: boolean; data: { hours: number; buckets: TimeseriesBucket[] } }>(
      `/api/v1/admin/metrics/timeseries?hours=${hours}`,
    ),
  monitoringAlerts: (status?: string) =>
    request<{
      success: boolean
      data: { alerts: AlertRow[]; count: number; total: number; active: number }
    }>(status ? `/api/v1/admin/alerts?status=${status}` : '/api/v1/admin/alerts'),
  acknowledgeAlert: (id: string) =>
    request<{ success: boolean; data: { alert: AlertRow } }>(
      `/api/v1/admin/alerts/${encodeURIComponent(id)}/acknowledge`,
      { method: 'POST' },
    ),
  monitoringRecentErrors: (limit = 20) =>
    request<{
      success: boolean
      data: { errors: MonitoringOverview['recent_errors']; count: number }
    }>(`/api/v1/admin/monitoring/recent-errors?limit=${limit}`),
}
