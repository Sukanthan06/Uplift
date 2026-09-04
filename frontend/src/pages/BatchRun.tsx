import { useRef, useState } from 'react'
import { API_BASE, type BatchAttemptEvent } from '../api'
import SectionCard from '../components/SectionCard'
import StatTile from '../components/StatTile'
import { formatInr, formatNumber } from '../format'

type StreamEvent =
  | { type: 'start'; total: number }
  | { type: 'attempt'; data: BatchAttemptEvent }
  | { type: 'error'; index: number; order_id: string; error: string }
  | { type: 'done'; total: number }

const SIZE_OPTIONS = [5, 10, 25, 50] as const

export default function BatchRun() {
  const [limit, setLimit] = useState<(typeof SIZE_OPTIONS)[number]>(5)
  const [running, setRunning] = useState(false)
  const [events, setEvents] = useState<StreamEvent[]>([])
  const startedAtRef = useRef<number | null>(null)
  const [durationMs, setDurationMs] = useState<number | null>(null)
  const sourceRef = useRef<EventSource | null>(null)

  function start() {
    setEvents([])
    setDurationMs(null)
    setRunning(true)
    startedAtRef.current = Date.now()
    const source = new EventSource(`${API_BASE}/batch/run?limit=${limit}`)
    sourceRef.current = source

    source.addEventListener('start', (e) => {
      const { total } = JSON.parse((e as MessageEvent).data)
      setEvents((prev) => [...prev, { type: 'start', total }])
    })
    source.addEventListener('attempt', (e) => {
      const data = JSON.parse((e as MessageEvent).data) as BatchAttemptEvent
      setEvents((prev) => [...prev, { type: 'attempt', data }])
    })
    source.addEventListener('error', (e) => {
      if ((e as MessageEvent).data) {
        const payload = JSON.parse((e as MessageEvent).data)
        setEvents((prev) => [...prev, { type: 'error', ...payload }])
      }
    })
    source.addEventListener('done', (e) => {
      const { total } = JSON.parse((e as MessageEvent).data)
      setEvents((prev) => [...prev, { type: 'done', total }])
      if (startedAtRef.current) setDurationMs(Date.now() - startedAtRef.current)
      source.close()
      setRunning(false)
    })
    source.onerror = () => {
      if (startedAtRef.current) setDurationMs(Date.now() - startedAtRef.current)
      source.close()
      setRunning(false)
    }
  }

  const attemptEvents = events.filter((e): e is { type: 'attempt'; data: BatchAttemptEvent } => e.type === 'attempt')
  const doneEvent = events.find((e): e is { type: 'done'; total: number } => e.type === 'done')
  const total = doneEvent?.total ?? limit
  const progressPct = events.length > 0 ? Math.min(100, (attemptEvents.length / total) * 100) : 0

  const retried = attemptEvents.filter((e) => e.data.chosen_action === 'retry')
  const recovered = retried
    .filter((e) => e.data.action_outcome === 'success')
    .reduce((sum, e) => sum + e.data.amount, 0)

  return (
    <div className="space-y-6">
      <SectionCard
        title="Batch Run"
        subtitle="Streams N failed attempts through the real pipeline live -- real Postgres, real Groq calls."
      >
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1 text-sm text-gray-600">
            Attempts
            <div className="ml-2 flex overflow-hidden rounded border border-gray-300">
              {SIZE_OPTIONS.map((size) => (
                <button
                  key={size}
                  onClick={() => setLimit(size)}
                  disabled={running}
                  className={`px-3 py-1 text-sm transition-colors ${
                    limit === size ? 'bg-gray-900 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'
                  } disabled:cursor-not-allowed`}
                >
                  {size}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={start}
            disabled={running}
            className="rounded bg-gray-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {running ? 'Running…' : 'Run batch'}
          </button>
        </div>

        {events.length > 0 && (
          <div className="mt-4">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
              <div
                className="h-full rounded-full bg-gray-900 transition-all"
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <div className="mt-1.5 text-xs text-gray-500">
              {formatNumber(attemptEvents.length, 0)} / {formatNumber(total, 0)} completed
            </div>
          </div>
        )}
      </SectionCard>

      {doneEvent && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <StatTile label="Recovered" value={formatInr(recovered)} sub="from successful retries" />
          <StatTile label="Retries sent" value={formatNumber(retried.length, 0)} />
          <StatTile
            label="Duration"
            value={durationMs !== null ? `${(durationMs / 1000).toFixed(1)}s` : '—'}
          />
        </div>
      )}

      {events.length > 0 && (
        <SectionCard title="Live results">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
                  <th className="py-2 pr-4">#</th>
                  <th className="py-2 pr-4">Payment ID</th>
                  <th className="py-2 pr-4 text-right">Amount</th>
                  <th className="py-2 pr-4">Diagnosis</th>
                  <th className="py-2 pr-4 text-right">Uplift (best)</th>
                  <th className="py-2 pr-4">Decision</th>
                  <th className="py-2 pr-4">Outcome</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {events.map((e, i) => {
                  if (e.type === 'attempt') {
                    const d = e.data
                    return (
                      <tr key={i} className="border-b border-gray-100 last:border-0">
                        <td className="py-2 pr-4">{d.index}</td>
                        <td className="py-2 pr-4 font-mono text-xs">{d.order_id.slice(0, 18)}…</td>
                        <td className="py-2 pr-4 text-right">{formatInr(d.amount)}</td>
                        <td className="py-2 pr-4">{d.cause_family}</td>
                        <td className="py-2 pr-4 text-right">{d.uplift_best.toFixed(3)}</td>
                        <td className="py-2 pr-4">
                          <span
                            className={
                              d.chosen_action === 'retry'
                                ? 'rounded-full bg-green-500/10 px-2 py-0.5 text-xs font-medium text-green-700'
                                : 'rounded-full bg-gray-500/10 px-2 py-0.5 text-xs font-medium text-gray-600'
                            }
                          >
                            {d.chosen_action}
                            {d.rules_fired.length > 0 ? ` (${d.rules_fired.join(', ')})` : ''}
                          </span>
                        </td>
                        <td className="py-2 pr-4">{d.action_outcome ?? '—'}</td>
                      </tr>
                    )
                  }
                  if (e.type === 'error') {
                    return (
                      <tr key={i} className="border-b border-gray-100 text-red-700">
                        <td className="py-2 pr-4">{e.index}</td>
                        <td colSpan={6} className="py-2 pr-4">
                          Attempt {e.order_id} failed: {e.error}
                        </td>
                      </tr>
                    )
                  }
                  return null
                })}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}
    </div>
  )
}
