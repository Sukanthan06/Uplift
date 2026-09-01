import { useRef, useState } from 'react'
import { API_BASE, type BatchAttemptEvent } from '../api'
import SectionCard from '../components/SectionCard'
import { formatNumber } from '../format'

type StreamEvent =
  | { type: 'start'; total: number }
  | { type: 'attempt'; data: BatchAttemptEvent }
  | { type: 'error'; index: number; order_id: string; error: string }
  | { type: 'done'; total: number }

export default function BatchRun() {
  const [limit, setLimit] = useState(5)
  const [running, setRunning] = useState(false)
  const [events, setEvents] = useState<StreamEvent[]>([])
  const sourceRef = useRef<EventSource | null>(null)

  function start() {
    setEvents([])
    setRunning(true)
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
      source.close()
      setRunning(false)
    })
    source.onerror = () => {
      source.close()
      setRunning(false)
    }
  }

  const attemptEvents = events.filter((e): e is { type: 'attempt'; data: BatchAttemptEvent } => e.type === 'attempt')
  const doneEvent = events.find((e): e is { type: 'done'; total: number } => e.type === 'done')

  return (
    <div className="space-y-6">
      <SectionCard
        title="Batch Run"
        subtitle="Streams N failed attempts through the real pipeline live -- real Postgres, real Groq calls."
      >
        <div className="flex items-center gap-3">
          <label className="text-sm text-gray-600">
            Attempts
            <input
              type="number"
              min={1}
              max={50}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              disabled={running}
              className="ml-2 w-20 rounded border border-gray-300 px-2 py-1 text-sm"
            />
          </label>
          <button
            onClick={start}
            disabled={running}
            className="rounded bg-gray-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {running ? 'Running…' : 'Run batch'}
          </button>
          {doneEvent && (
            <span className="text-sm text-gray-500">
              {formatNumber(attemptEvents.length, 0)} / {formatNumber(doneEvent.total, 0)} completed
            </span>
          )}
        </div>
      </SectionCard>

      {events.length > 0 && (
        <SectionCard title="Live results">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
                  <th className="py-2 pr-4">#</th>
                  <th className="py-2 pr-4">Order</th>
                  <th className="py-2 pr-4">Method</th>
                  <th className="py-2 pr-4">Error code</th>
                  <th className="py-2 pr-4">Cause family</th>
                  <th className="py-2 pr-4">Decision</th>
                  <th className="py-2 pr-4">Uplift best</th>
                  <th className="py-2 pr-4">Action</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {events.map((e, i) => {
                  if (e.type === 'attempt') {
                    const d = e.data
                    return (
                      <tr key={i} className="border-b border-gray-100">
                        <td className="py-2 pr-4">{d.index}</td>
                        <td className="py-2 pr-4 font-mono text-xs">{d.order_id.slice(0, 18)}…</td>
                        <td className="py-2 pr-4">{d.method}</td>
                        <td className="py-2 pr-4">{d.error_code}</td>
                        <td className="py-2 pr-4">{d.cause_family}</td>
                        <td className="py-2 pr-4">
                          <span
                            className={
                              d.chosen_action === 'retry'
                                ? 'rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800'
                                : 'rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700'
                            }
                          >
                            {d.chosen_action}
                            {d.rules_fired.length > 0 ? ` (${d.rules_fired.join(', ')})` : ''}
                          </span>
                        </td>
                        <td className="py-2 pr-4">{d.uplift_best.toFixed(3)}</td>
                        <td className="py-2 pr-4">{d.action_outcome ?? '—'}</td>
                      </tr>
                    )
                  }
                  if (e.type === 'error') {
                    return (
                      <tr key={i} className="border-b border-gray-100 text-red-700">
                        <td className="py-2 pr-4">{e.index}</td>
                        <td colSpan={7} className="py-2 pr-4">
                          error on {e.order_id}: {e.error}
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
