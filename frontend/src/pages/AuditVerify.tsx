import { useEffect, useState } from 'react'
import { fetchAuditVerify, type AuditVerifyResponse } from '../api'
import SectionCard from '../components/SectionCard'
import StatTile from '../components/StatTile'
import { status } from '../colors'

export default function AuditVerify() {
  const [data, setData] = useState<AuditVerifyResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  function load() {
    setLoading(true)
    fetchAuditVerify()
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  if (error) {
    return <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
  }

  return (
    <div className="space-y-6">
      <SectionCard
        title="Audit chain verification"
        subtitle='Never "immutable" -- Postgres rows can always be edited. This is tamper-EVIDENCE: verify() walks the hash chain and reports exactly where it breaks.'
      >
        <div className="flex items-center gap-3">
          <button
            onClick={load}
            disabled={loading}
            className="rounded bg-gray-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {loading ? 'Verifying…' : 'Re-verify'}
          </button>
          <span className="text-xs text-gray-500">GET /audit/verify</span>
        </div>
      </SectionCard>

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <StatTile label="Total records" value={String(data.total_records)} />
            <StatTile
              label="Chain status"
              value={data.all_valid ? 'Valid' : 'Broken'}
            />
            <StatTile
              label="First invalid record"
              value={data.first_invalid_id === null ? '—' : `#${data.first_invalid_id}`}
            />
          </div>

          <SectionCard title="Records">
            {data.records.length === 0 && (
              <p className="text-sm text-gray-500">
                No audit events yet -- run a batch on the Batch Run page first.
              </p>
            )}
            <ul className="divide-y divide-gray-100">
              {data.records.map((r) => (
                <li key={r.id} className="flex items-center gap-3 py-2 text-sm">
                  <span
                    className="inline-block h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: r.valid ? status.good : status.critical }}
                  />
                  <span className="font-mono text-xs text-gray-500">#{r.id}</span>
                  <span className={r.valid ? 'text-gray-700' : 'font-medium text-red-700'}>
                    {r.valid ? 'valid' : r.reason}
                  </span>
                </li>
              ))}
            </ul>
          </SectionCard>
        </>
      )}
    </div>
  )
}
