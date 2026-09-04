import { useEffect, useState } from 'react'
import {
  fetchDecisionDetail,
  fetchDecisions,
  type DecisionDetail as DecisionDetailType,
  type DecisionSummary,
} from '../api'
import SectionCard from '../components/SectionCard'
import { formatInr, formatTimestamp } from '../format'

function ActionBadge({ action }: { action: string }) {
  return (
    <span
      className={
        action === 'retry'
          ? 'rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800'
          : 'rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700'
      }
    >
      {action}
    </span>
  )
}

export default function DecisionDetail() {
  const [decisions, setDecisions] = useState<DecisionSummary[]>([])
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<DecisionDetailType | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchDecisions()
      .then((rows) => {
        setDecisions(rows)
        if (rows.length > 0) setSelectedId(rows[0].decision_id)
      })
      .catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    if (selectedId === null) return
    fetchDecisionDetail(selectedId)
      .then(setDetail)
      .catch((e) => setError(String(e)))
  }, [selectedId])

  if (error) {
    return <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
  }

  const filtered = decisions.filter((d) =>
    d.order_id.toLowerCase().includes(query.trim().toLowerCase())
  )

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <SectionCard title={`Decisions (${decisions.length})`}>
        {decisions.length === 0 ? (
          <p className="text-sm text-gray-500">
            None yet -- run a batch on the Batch Run page first.
          </p>
        ) : (
          <>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by payment ID"
              aria-label="Search by payment ID"
              className="mb-3 w-full rounded border border-gray-300 px-3 py-1.5 text-sm placeholder:text-gray-400"
            />
            {filtered.length === 0 && (
              <p className="text-sm text-gray-500">No payment ID matches "{query}".</p>
            )}
          </>
        )}
        <ul className="max-h-[32rem] divide-y divide-gray-100 overflow-y-auto">
          {filtered.map((d) => (
            <li key={d.decision_id}>
              <button
                onClick={() => setSelectedId(d.decision_id)}
                className={`block w-full px-1 py-2 text-left text-sm hover:bg-gray-50 ${
                  selectedId === d.decision_id ? 'bg-gray-50' : ''
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-gray-500">
                    {d.order_id.slice(0, 14)}…
                  </span>
                  <ActionBadge action={d.chosen_action} />
                </div>
                <div className="mt-0.5 text-gray-700">
                  {d.method} · {d.error_code} · {formatInr(d.amount)}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </SectionCard>

      <div className="lg:col-span-2 space-y-6">
        {!detail && <p className="text-sm text-gray-500">Select a decision to see its full trail.</p>}
        {detail && (
          <>
            <SectionCard title="Payment & decision">
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                <dt className="text-gray-500">Order</dt>
                <dd className="font-mono text-xs">{detail.order_id}</dd>
                <dt className="text-gray-500">Method / error code</dt>
                <dd>
                  {detail.method} / {detail.error_code}
                </dd>
                <dt className="text-gray-500">Amount</dt>
                <dd>{formatInr(detail.amount)}</dd>
                <dt className="text-gray-500">uplift(now) / uplift(best)</dt>
                <dd>
                  {detail.uplift_now.toFixed(4)} / {detail.uplift_best.toFixed(4)}
                </dd>
                <dt className="text-gray-500">Chosen action</dt>
                <dd>
                  <ActionBadge action={detail.chosen_action} />
                </dd>
                <dt className="text-gray-500">Rules fired</dt>
                <dd>{detail.rules_fired.length > 0 ? detail.rules_fired.join(', ') : '—'}</dd>
                <dt className="text-gray-500">Policy version</dt>
                <dd>{detail.policy_version}</dd>
              </dl>
            </SectionCard>

            <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
              <SectionCard title="Reconciliation">
                {detail.reconciliation ? (
                  <p className="text-sm">
                    gateway reported <strong>{detail.reconciliation.gateway_reported_status}</strong>
                  </p>
                ) : (
                  <p className="text-sm text-gray-500">none</p>
                )}
              </SectionCard>
              <SectionCard title="Diagnosis">
                {detail.diagnosis ? (
                  <div className="space-y-1 text-sm">
                    <p>
                      <strong>{detail.diagnosis.cause_family}</strong> (
                      {(detail.diagnosis.confidence * 100).toFixed(0)}% confidence)
                    </p>
                    <p className="text-gray-600">{detail.diagnosis.root_cause}</p>
                  </div>
                ) : (
                  <p className="text-sm text-gray-500">none</p>
                )}
              </SectionCard>
              <SectionCard title="Action">
                {detail.action ? (
                  <p className="text-sm">
                    {detail.action.outcome}
                    {detail.action.http_status ? ` (HTTP ${detail.action.http_status})` : ''}, attempt #
                    {detail.action.api_attempt_no}
                  </p>
                ) : (
                  <p className="text-sm text-gray-500">no retry executed</p>
                )}
              </SectionCard>
            </div>

            <SectionCard
              title="Audit trail"
              subtitle="Every hash-chained event this decision produced, in order"
            >
              <ol className="space-y-2">
                {detail.audit_trail.map((event) => (
                  <li key={event.id} className="rounded border border-gray-100 bg-gray-50 p-2 text-xs">
                    <span className="font-mono text-gray-400">#{event.id}</span>{' '}
                    <span className="font-medium">{String(event.payload_json.event)}</span>{' '}
                    <span className="text-gray-500">{formatTimestamp(event.created_at)}</span>
                  </li>
                ))}
              </ol>
            </SectionCard>
          </>
        )}
      </div>
    </div>
  )
}
