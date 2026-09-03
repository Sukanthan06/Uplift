import { useEffect, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchOverview, type OverviewResponse } from '../api'
import { categorical, diverging, ink, policyColor } from '../colors'
import { formatNumber, formatPct } from '../format'
import PolicyTable from '../components/PolicyTable'
import SectionCard from '../components/SectionCard'
import StatTile from '../components/StatTile'

const BASELINE_ORDER = ['do_nothing', 'retry_once', 'retry_3x', 'rule_based', 'uplift_ranked']

function marginColor(margin: number | null, bound: number): string {
  if (margin === null) return '#f4f4f2'
  const t = Math.max(-1, Math.min(1, margin / bound))
  // interpolate: negative -> red, positive -> blue, 0 -> gray midpoint
  const target = t >= 0 ? diverging.positive : diverging.negative
  const mix = Math.abs(t)
  const from = hexToRgb(diverging.midpoint)
  const to = hexToRgb(target)
  const r = Math.round(from.r + (to.r - from.r) * mix)
  const g = Math.round(from.g + (to.g - from.g) * mix)
  const b = Math.round(from.b + (to.b - from.b) * mix)
  return `rgb(${r},${g},${b})`
}

function hexToRgb(hex: string) {
  const n = parseInt(hex.replace('#', ''), 16)
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }
}

export default function Overview() {
  const [data, setData] = useState<OverviewResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchOverview()
      .then(setData)
      .catch((e) => setError(String(e)))
  }, [])

  if (error) {
    return <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
  }
  if (!data) {
    return <div className="text-sm text-gray-500">Loading...</div>
  }

  const heatmapBound = Math.max(
    1,
    ...data.phase4_sweeps
      ? data.phase4_sweeps.heatmap.margins.flat().filter((m): m is number => m !== null).map(Math.abs)
      : [1]
  )

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <StatTile label="Total attempts" value={formatNumber(data.simulator.total_attempts, 0)} />
        <StatTile label="Failed attempts" value={formatNumber(data.simulator.failed_attempts, 0)} />
        <StatTile
          label="Audit chain"
          value={data.pipeline_activity.audit_all_valid ? 'Valid' : 'BROKEN'}
          sub={`${data.pipeline_activity.audit_records} records`}
        />
        <StatTile
          label="Live decisions"
          value={formatNumber(
            Object.values(data.pipeline_activity.decisions_by_action).reduce((a, b) => a + b, 0),
            0
          )}
          sub="from Batch Run"
        />
        <StatTile
          label="Open incidents"
          value={formatNumber(data.pipeline_activity.open_incidents, 0)}
          sub="retry budget exhausted"
        />
      </div>

      <SectionCard
        title="Phase 2 — baseline comparison"
        subtitle="do-nothing / retry-once / retry-3x / rule-based, no ML involved"
      >
        <PolicyTable scores={data.phase2_baselines} order={BASELINE_ORDER} />
      </SectionCard>

      {data.phase3 && (
        <SectionCard
          title="Phase 3 — uplift model, held-out test set"
          subtitle={`${data.phase3.n_test} test attempts. Reported honestly: the model is compared against rule_based at matched budget, win or lose.`}
        >
          <PolicyTable scores={data.phase3.baselines} order={BASELINE_ORDER} />
          <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-3">
            <div className="md:col-span-1">
              <StatTile
                label="uplift@20%"
                value={formatNumber(data.phase3.uplift_at_20pct, 2)}
                sub="observed-outcome delta, top 20% by predicted uplift"
              />
            </div>
            <div className="md:col-span-2">
              <div className="mb-1 text-xs font-medium uppercase tracking-wide text-gray-500">
                Qini curve
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={data.phase3.qini_curve.map(([k, q]) => ({ k, q }))}>
                  <CartesianGrid stroke={ink.gridline} vertical={false} />
                  <XAxis
                    dataKey="k"
                    tickFormatter={(v) => formatPct(v, 0)}
                    stroke={ink.muted}
                    fontSize={11}
                  />
                  <YAxis stroke={ink.muted} fontSize={11} width={40} />
                  <Tooltip
                    formatter={(v: number) => formatNumber(v, 1)}
                    labelFormatter={(v) => `top ${formatPct(v as number, 0)}`}
                  />
                  <Line
                    type="monotone"
                    dataKey="q"
                    stroke={categorical.blue}
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </SectionCard>
      )}
      {!data.phase3 && (
        <SectionCard title="Phase 3 — uplift model">
          <p className="text-sm text-gray-500">
            No trained model found. Run <code>python -m ml.train_uplift</code> in the backend.
          </p>
        </SectionCard>
      )}

      {data.phase4_sweeps && (
        <SectionCard
          title="Phase 4 — sensitivity sweep"
          subtitle="uplift_ranked vs rule_based advantage across swept sim_config parameters"
        >
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            {Object.entries(data.phase4_sweeps.sweeps).map(([name, sweep]) => (
              <div key={name}>
                <div className="mb-1 text-xs font-medium text-gray-600">{sweep.label}</div>
                <ResponsiveContainer width="100%" height={160}>
                  <LineChart data={sweep.points.map((p) => ({ value: p.value, ...p.recovered_inr }))}>
                    <CartesianGrid stroke={ink.gridline} vertical={false} />
                    <XAxis dataKey="value" stroke={ink.muted} fontSize={10} />
                    <YAxis stroke={ink.muted} fontSize={10} width={36} tick={false} />
                    <Tooltip formatter={(v: number) => formatNumber(v, 0)} />
                    {BASELINE_ORDER.map((policy) => (
                      <Line
                        key={policy}
                        type="monotone"
                        dataKey={policy}
                        stroke={policyColor[policy]}
                        strokeWidth={1.5}
                        dot={false}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ))}
          </div>

          <div className="mt-6">
            <div className="mb-2 text-xs font-medium text-gray-600">
              {data.phase4_sweeps.heatmap.param_a.label} × {data.phase4_sweeps.heatmap.param_b.label}
              {' — uplift_ranked advantage over rule_based (%)'}
            </div>
            <div className="overflow-x-auto">
              <table className="text-xs">
                <thead>
                  <tr>
                    <th />
                    {data.phase4_sweeps.heatmap.values_b.map((v) => (
                      <th key={v} className="px-2 py-1 font-normal text-gray-500">
                        {v}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.phase4_sweeps.heatmap.values_a.map((va, i) => (
                    <tr key={va}>
                      <td className="pr-2 text-right font-normal text-gray-500">{va}</td>
                      {data.phase4_sweeps!.heatmap.margins[i].map((m, j) => (
                        <td
                          key={j}
                          className="px-2 py-1 text-center tabular-nums"
                          style={{ backgroundColor: marginColor(m, heatmapBound) }}
                        >
                          {m === null ? 'n/a' : `${m > 0 ? '+' : ''}${m.toFixed(1)}%`}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </SectionCard>
      )}
    </div>
  )
}
