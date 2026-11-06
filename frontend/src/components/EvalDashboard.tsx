// Evaluation dashboard — real GET /api/v1/eval/results, with a
// "Run evaluation" button (slow, minutes). Metrics are shown as CSS
// bars sized from the real values, with targets alongside. Used by
// both the Admin page and the /evaluation route.
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type EvalReport } from '../api/client'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { CardSkeleton } from '../components/Skeleton'
import { useToast } from '../components/Toast'

function MetricBar({
  label,
  value,
  target,
  passed,
}: {
  label: string
  value: number
  target: number
  passed: boolean | undefined
}) {
  const pct = Math.max(0, Math.min(100, value * 100))
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-medium text-navy-900">{label}</span>
        <span className="text-slate-600">
          {value.toFixed(4)} <span className="text-xs">(target ≥ {target})</span>{' '}
          <span className={passed ? 'font-semibold text-emerald-700' : 'font-semibold text-red-700'}>
            {passed === undefined ? '' : passed ? 'PASS' : 'MISS'}
          </span>
        </span>
      </div>
      <div className="mt-1 h-3 w-full overflow-hidden rounded-full bg-slate-200">
        <div
          className={`h-full rounded-full ${passed ? 'bg-emerald-500' : 'bg-red-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

export default function EvalDashboard() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const [report, setReport] = useState<EvalReport | null>(null)
  const [missing, setMissing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.evalResults()
      if (res.success && res.data) {
        setReport(res.data)
        setMissing(false)
      } else {
        setMissing(true)
      }
    } catch (e) {
      if (e instanceof Error && e.message === 'UNAUTHORIZED') {
        navigate('/login')
        return
      }
      setError(e instanceof Error ? e.message : 'Could not load evaluation results')
    } finally {
      setLoading(false)
    }
  }, [navigate])

  useEffect(() => {
    void load()
  }, [load])

  async function runEval() {
    setRunning(true)
    setMissing(false)
    try {
      const res = await api.evalRun()
      setReport(res.data)
      toast('Evaluation finished.', 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Evaluation could not run.', 'error')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div>
      <p className="text-xs text-slate-500">
        Local RAGAS-style scores (no LLM judge — see docs/SPRINT4.md). Targets: faithfulness ≥ 0.85,
        context recall ≥ 0.80, answer relevancy ≥ 0.85.
      </p>

      {loading && (
        <div className="mt-4 space-y-3">
          <CardSkeleton />
          <CardSkeleton />
        </div>
      )}
      {!loading && error && <ErrorState message={error} onRetry={() => void load()} />}
      {!loading && !error && missing && !report && (
        <div className="mt-4">
          <EmptyState
            title="No evaluation run yet"
            message="No evaluation has been run in this environment. A run asks 20 questions and takes 2–4 minutes."
            action={
              <button
                type="button"
                onClick={() => void runEval()}
                disabled={running}
                className="rounded-lg bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-50"
              >
                {running ? 'Running…' : 'Run evaluation'}
              </button>
            }
          />
        </div>
      )}
      {running && (
        <p className="mt-4 rounded-xl border bg-white p-4 text-sm text-slate-600 shadow-sm">
          Evaluation running… 20 questions, 2–4 minutes. Do not close this page.
        </p>
      )}
      {!loading && !error && report && (
        <div className="mt-4 space-y-5">
          <div className="rounded-xl border bg-white p-5 shadow-sm">
            <p className="text-sm text-slate-600">
              Run: {new Date(report.run_at).toLocaleString()} · {report.run_seconds}s ·{' '}
              {report.question_count} questions ·{' '}
              {report.all_targets_met ? (
                <span className="font-semibold text-emerald-700">All targets met</span>
              ) : (
                <span className="font-semibold text-red-700">Some targets missed — reported as-is</span>
              )}
            </p>
            <div className="mt-4 space-y-4">
              <MetricBar
                label="Faithfulness"
                value={report.aggregates.faithfulness}
                target={report.targets.faithfulness}
                passed={report.verdict_vs_targets.faithfulness}
              />
              <MetricBar
                label="Context recall"
                value={report.aggregates.context_recall}
                target={report.targets.context_recall}
                passed={report.verdict_vs_targets.context_recall}
              />
              <MetricBar
                label="Answer relevancy"
                value={report.aggregates.answer_relevancy}
                target={report.targets.answer_relevancy}
                passed={report.verdict_vs_targets.answer_relevancy}
              />
              <MetricBar
                label="Top-doc accuracy"
                value={report.aggregates.top_doc_accuracy}
                target={0}
                passed={undefined}
              />
            </div>
            <div className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
              <div className="rounded-lg bg-slate-50 px-3 py-2">
                <span className="text-slate-500">Latency p50</span>
                <p className="font-semibold text-navy-900">{report.aggregates.latency_ms_p50} ms</p>
              </div>
              <div className="rounded-lg bg-slate-50 px-3 py-2">
                <span className="text-slate-500">Latency p95</span>
                <p className="font-semibold text-navy-900">{report.aggregates.latency_ms_p95} ms</p>
              </div>
              <div className="rounded-lg bg-slate-50 px-3 py-2">
                <span className="text-slate-500">Refused</span>
                <p className="font-semibold text-navy-900">
                  {report.aggregates.refused_count} of {report.question_count}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => void runEval()}
              disabled={running}
              className="mt-4 rounded-lg bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-50"
            >
              {running ? 'Running…' : 'Run evaluation again'}
            </button>
          </div>

          <div className="overflow-x-auto rounded-xl border bg-white shadow-sm">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-slate-50 text-left">
                  <th className="px-3 py-2 font-semibold text-navy-900">Q</th>
                  <th className="px-3 py-2 font-semibold text-navy-900">Top doc</th>
                  <th className="px-3 py-2 font-semibold text-navy-900">Faith.</th>
                  <th className="px-3 py-2 font-semibold text-navy-900">Recall</th>
                  <th className="px-3 py-2 font-semibold text-navy-900">Relev.</th>
                  <th className="px-3 py-2 font-semibold text-navy-900">Phrase</th>
                </tr>
              </thead>
              <tbody>
                {report.questions.map((q) => (
                  <tr key={q.id} className="border-b last:border-0">
                    <td className="px-3 py-2">{q.id}</td>
                    <td className="px-3 py-2">{q.top_document ?? '—'}</td>
                    <td className="px-3 py-2">{q.faithfulness.toFixed(2)}</td>
                    <td className="px-3 py-2">{q.context_recall.toFixed(0)}</td>
                    <td className="px-3 py-2">{q.answer_relevancy.toFixed(2)}</td>
                    <td className="px-3 py-2">{q.phrase_present ? 'yes' : 'no'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
