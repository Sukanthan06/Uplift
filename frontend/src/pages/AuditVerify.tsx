import { useEffect, useState } from 'react'
import { fetchAuditVerify, type AuditVerifyResponse } from '../api'
import SectionCard from '../components/SectionCard'
import StatTile from '../components/StatTile'
import { status } from '../colors'
import { formatNumber, formatTimestamp } from '../format'

export default function AuditVerify() {
  const [data, setData] = useState<AuditVerifyResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [lastVerifiedAt, setLastVerifiedAt] = useState<Date | null>(null)

  function load() {
    setLoading(true)
    fetchAuditVerify()
      .then((res) => {
        setData(res)
        setLastVerifiedAt(new Date())
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  if (error) {
    return <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
  }

  const recentRecords = data ? data.records.slice(-20).reverse() : []

  return (
    <div className="space-y-6">
      {data && (
        <div
          className={`rounded-lg border p-8 text-center ${
            data.all_valid ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'
          }`}
        >
          <div
            className={`text-4xl font-semibold ${data.all_valid ? 'text-green-700' : 'text-red-700'}`}
          >
            {data.all_valid ? '✓ Chain verified' : '✗ Chain compromised'}
          </div>
          <div className="mt-2 text-sm text-gray-600">
            {formatNumber(data.total_records, 0)} records checked
            {!data.all_valid && data.first_invalid_id !== null && (
              <> &middot; breach at record #{data.first_invalid_id}</>
            )}
            {lastVerifiedAt && <> &middot; last verified {formatTimestamp(lastVerifiedAt)}</>}
          </div>
        </div>
      )}

      <SectionCard
        title="Re-run verification"
        subtitle='Never "immutable" -- Postgres rows can always be edited. This is tamper-evidence: verify() walks the hash chain and reports exactly where it breaks.'
      >
        <div className="flex items-center gap-3">
          <button
            onClick={load}
            disabled={loading}
            className="rounded bg-gray-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {loading ? 'Verifying…' : 'Verify chain'}
          </button>
          <span className="text-xs text-gray-500">GET /audit/verify</span>
        </div>
      </SectionCard>

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <StatTile label="Total records" value={formatNumber(data.total_records, 0)} />
            <StatTile
              label="Chain status"
              value={data.all_valid ? 'Valid' : 'Broken'}
            />
            <StatTile
              label="First invalid record"
              value={data.first_invalid_id === null ? '—' : `#${data.first_invalid_id}`}
            />
          </div>

          <SectionCard
            title="Recent records"
            subtitle={
              data.records.length > 20
                ? `Most recent 20 of ${formatNumber(data.records.length, 0)}, newest first`
                : 'Newest first'
            }
          >
            {data.records.length === 0 && (
              <p className="text-sm text-gray-500">
                No audit events yet. Run a batch on the Batch Run page first.
              </p>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
                    <th className="py-2 pr-4">ID</th>
                    <th className="py-2 pr-4">Payment</th>
                    <th className="py-2 pr-4">Event</th>
                    <th className="py-2 pr-4">Hash</th>
                    <th className="py-2 pr-4">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {recentRecords.map((r, i) => {
                    // Once the chain is broken, every record from the first
                    // invalid one onward is untrustworthy -- distinguish the
                    // exact breach (red) from downstream fallout (amber).
                    const isBreach = r.id === data.first_invalid_id
                    const color = r.valid ? status.good : isBreach ? status.critical : status.warning
                    return (
                      <tr key={i} className="border-b border-gray-100 last:border-0">
                        <td className="py-2 pr-4 font-mono text-xs text-gray-500">#{r.id}</td>
                        <td className="py-2 pr-4 font-mono text-xs text-gray-600">
                          {r.order_id ? `${r.order_id.slice(0, 14)}…` : '—'}
                        </td>
                        <td className="py-2 pr-4 text-gray-700">{r.event ?? '—'}</td>
                        <td className="py-2 pr-4 font-mono text-xs text-gray-400">
                          {r.hash.slice(0, 10)}…
                        </td>
                        <td className="py-2 pr-4">
                          <span className="inline-flex items-center gap-1.5">
                            <span
                              className="inline-block h-2 w-2 shrink-0 rounded-full"
                              style={{ backgroundColor: color }}
                            />
                            <span
                              className={
                                r.valid
                                  ? 'text-gray-700'
                                  : isBreach
                                    ? 'font-medium text-red-700'
                                    : 'text-amber-700'
                              }
                            >
                              {r.valid ? 'valid' : r.reason}
                            </span>
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </SectionCard>
        </>
      )}
    </div>
  )
}
