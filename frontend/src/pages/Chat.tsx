// Chat ("/chat") — real POST /api/v1/chat, no fake answers. Citations
// are real chunks (title + page + score + department). RBAC refusals
// show as an amber warning card. History is kept in localStorage per
// user and loaded on mount; "New chat" clears it.
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, getStoredUser, roleLabel, type ChatResponse, type Citation } from '../api/client'
import { useToast } from '../components/Toast'

interface Message {
  role: 'user' | 'assistant'
  text: string
  citations?: Citation[]
  generationMode?: string
  latencyMs?: number
  retrievedCount?: number
  refused?: boolean
  messageId?: string
  feedback?: 'up' | 'down' | null
}

const SUGGESTED = [
  'What documents are needed for KYC account opening?',
  'What is the AML reporting threshold?',
  'ما هي شروط القرض الشخصي؟',
  'كم عدد أيام الإجازة السنوية؟',
]

const LAST_MODE_KEY = 'rtb_last_generation_mode'

function historyKey(email: string): string {
  return `rtb_chat_history_${email}`
}

export default function Chat() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const me = getStoredUser()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const [conversationId, setConversationId] = useState<string | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [sendingFeedback, setSendingFeedback] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Load this user's saved history on mount.
  useEffect(() => {
    if (!me) return
    try {
      const raw = localStorage.getItem(historyKey(me.email))
      if (raw) {
        const saved = JSON.parse(raw) as Message[]
        if (Array.isArray(saved)) setMessages(saved)
      }
    } catch {
      // Corrupt saved history — start fresh.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Persist history whenever it changes.
  useEffect(() => {
    if (!me) return
    try {
      localStorage.setItem(historyKey(me.email), JSON.stringify(messages))
    } catch {
      // Storage full or unavailable — chat still works.
    }
  }, [messages, me])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, thinking])

  function newChat() {
    setMessages([])
    setConversationId(undefined)
    setError(null)
    if (me) localStorage.removeItem(historyKey(me.email))
  }

  async function copyAnswer(msg: Message) {
    try {
      await navigator.clipboard.writeText(msg.text)
      setCopiedId(msg.messageId ?? msg.text.slice(0, 32))
      window.setTimeout(() => setCopiedId(null), 2000)
    } catch {
      toast('Could not copy — clipboard is not available.', 'error')
    }
  }

  async function sendFeedback(index: number, rating: 'up' | 'down') {
    const msg = messages[index]
    if (!msg?.messageId || sendingFeedback) return
    setSendingFeedback(msg.messageId)
    try {
      await api.feedback(msg.messageId, rating)
      setMessages((m) => m.map((x, j) => (j === index ? { ...x, feedback: rating } : x)))
      toast('Thank you, your feedback was received.', 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Feedback could not be sent.', 'error')
    } finally {
      setSendingFeedback(null)
    }
  }

  async function ask(question?: string) {
    const q = (question ?? input).trim()
    if (!q || thinking) return
    setInput('')
    setError(null)
    setMessages((m) => [...m, { role: 'user', text: q }])
    setThinking(true)
    try {
      const res: ChatResponse = await api.chat(q, conversationId)
      setConversationId(res.data.conversation_id)
      try {
        localStorage.setItem(LAST_MODE_KEY, res.data.generation_mode)
      } catch {
        // ignore
      }
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          text: res.data.answer,
          citations: res.data.citations,
          generationMode: res.data.generation_mode,
          latencyMs: res.data.latency_ms,
          retrievedCount: res.data.retrieved_count,
          refused: res.data.refused,
          messageId: res.data.message_id,
          feedback: null,
        },
      ])
    } catch (e) {
      if (e instanceof Error && e.message === 'UNAUTHORIZED') {
        navigate('/login')
        return
      }
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setThinking(false)
    }
  }

  const isArabic = (text: string) => /[\u0600-\u06FF]/.test(text)

  const modeLabel = (mode?: string) =>
    mode === 'ollama'
      ? 'LLM (Ollama)'
      : mode === 'extractive-fallback'
        ? 'Grounded extract — no LLM running'
        : mode === 'rbac-refusal'
          ? 'No access to this topic'
          : mode ?? ''

  return (
    <section className="flex h-full flex-col">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-navy-900">Chat — Enterprise Intelligence</h1>
          <p className="mt-1 text-sm text-slate-600">
            Answers come only from the indexed bank documents, with citations.
            {me && (
              <>
                {' '}
                You are signed in as <strong>{me.name}</strong> ({roleLabel(me.role)}) — you can see:{' '}
                {me.departments.join(', ')}.
              </>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={newChat}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-navy-900 hover:bg-slate-50"
        >
          New chat
        </button>
      </div>

      {messages.length === 0 && !thinking && (
        <div className="mb-4 rounded-xl border bg-white p-5 shadow-sm">
          <p className="text-sm font-semibold text-navy-900">Try one of these:</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {SUGGESTED.map((s) => (
              <button
                key={s}
                type="button"
                dir={isArabic(s) ? 'rtl' : 'ltr'}
                onClick={() => void ask(s)}
                className="rounded-full border border-navy-200 bg-navy-50 px-3 py-1.5 text-sm text-navy-900 hover:bg-navy-100"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex-1 space-y-4 overflow-y-auto pb-4">
        {messages.map((msg, i) => (
          <div
            key={i}
            dir={isArabic(msg.text) ? 'rtl' : 'ltr'}
            className={`max-w-3xl rounded-xl border p-4 shadow-sm ${
              msg.role === 'user'
                ? 'ml-auto bg-navy-900 text-white'
                : msg.refused
                  ? 'border-amber-300 bg-amber-50'
                  : 'bg-white'
            }`}
          >
            <p className={`text-xs font-semibold ${msg.role === 'user' ? 'text-slate-300' : 'text-slate-500'}`}>
              {msg.role === 'user' ? 'You' : 'Riyadh Trust Bank Assistant'}
            </p>
            {msg.refused && (
              <p className="mt-2 rounded-lg bg-amber-100 px-3 py-2 text-sm font-medium text-amber-900">
                ⚠️ Your role does not have access to this topic. Ask about a document your role can see,
                or contact an Admin.
              </p>
            )}
            <p className="mt-1 whitespace-pre-line text-sm leading-relaxed">{msg.text}</p>

            {msg.citations && msg.citations.length > 0 && (
              <div className="mt-3">
                <p className="mb-2 text-xs font-semibold text-slate-500">Sources</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {msg.citations.map((c, j) => (
                    <div key={j} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                      <p className="text-sm font-medium text-navy-900">{c.document_title}</p>
                      <p className="mt-0.5 text-xs text-slate-600">
                        Page {c.page_no ?? '—'}
                        {c.score !== null && c.score !== undefined
                          ? ` · score ${Number(c.score).toFixed(4)}`
                          : ''}
                      </p>
                      <span className="mt-1 inline-block rounded-full bg-teal-100 px-2 py-0.5 text-xs font-medium text-teal-800">
                        {c.department}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {msg.generationMode && (
              <p className="mt-2 text-xs text-slate-500">
                <span className="rounded-full bg-teal-100 px-2 py-0.5 text-teal-800">{modeLabel(msg.generationMode)}</span>{' '}
                {msg.latencyMs !== undefined && `${msg.latencyMs} ms`}
                {msg.retrievedCount !== undefined && ` · ${msg.retrievedCount} sources retrieved`}
              </p>
            )}

            {msg.role === 'assistant' && (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => void copyAnswer(msg)}
                  className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-navy-900 hover:bg-slate-50"
                >
                  {copiedId === (msg.messageId ?? msg.text.slice(0, 32)) ? 'Copied ✓' : 'Copy answer'}
                </button>
                {msg.messageId && (
                  <>
                    <span className="text-xs text-slate-500">Was this answer helpful?</span>
                    <button
                      type="button"
                      className={`rounded-lg border px-2 py-1 text-sm ${
                        msg.feedback === 'up' ? 'border-emerald-400 bg-emerald-100' : 'bg-white'
                      }`}
                      disabled={sendingFeedback === msg.messageId}
                      onClick={() => void sendFeedback(i, 'up')}
                      aria-label="Thumbs up"
                    >
                      👍
                    </button>
                    <button
                      type="button"
                      className={`rounded-lg border px-2 py-1 text-sm ${
                        msg.feedback === 'down' ? 'border-red-400 bg-red-100' : 'bg-white'
                      }`}
                      disabled={sendingFeedback === msg.messageId}
                      onClick={() => void sendFeedback(i, 'down')}
                      aria-label="Thumbs down"
                    >
                      👎
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        ))}

        {thinking && (
          <div className="max-w-3xl rounded-xl border bg-white p-4 shadow-sm">
            <p className="text-sm text-slate-600">
              Thinking
              <span className="typing-dots" aria-hidden="true">
                <span>.</span>
                <span>.</span>
                <span>.</span>
              </span>
            </p>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {error && (
        <p className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}

      <div className="flex gap-2">
        <input
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
          value={input}
          disabled={thinking}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void ask()
          }}
          placeholder="Ask about KYC, AML, loans, leave, fees… (English or العربية)"
        />
        <button
          type="button"
          className="rounded-lg bg-navy-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-50"
          disabled={thinking || !input.trim()}
          onClick={() => void ask()}
        >
          Ask
        </button>
      </div>
      <p className="mt-2 text-xs text-slate-500">
        RBAC enforced — you only see documents your role is allowed to see. Answers are grounded in
        the indexed documents only.
      </p>
    </section>
  )
}
