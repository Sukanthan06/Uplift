import type { PolicyScore } from '../api'
import { policyColor } from '../colors'
import { formatInr, formatNumber } from '../format'

interface PolicyTableProps {
  scores: Record<string, PolicyScore>
  order: string[]
}

export default function PolicyTable({ scores, order }: PolicyTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
            <th className="py-2 pr-4">Policy</th>
            <th className="py-2 pr-4 text-right">Recovered</th>
            <th className="py-2 pr-4 text-right">Retries</th>
            <th className="py-2 pr-4 text-right">Cost / ₹ recovered</th>
            <th className="py-2 pr-4 text-right">Customer contacts</th>
            <th className="py-2 pr-4 text-right">Double-charge near-misses</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {order
            .filter((name) => scores[name])
            .map((name) => {
              const s = scores[name]
              return (
                <tr key={name} className="border-b border-gray-100 last:border-0">
                  <td className="py-2 pr-4 font-medium text-gray-900">
                    <span
                      className="mr-2 inline-block h-2.5 w-2.5 rounded-full align-middle"
                      style={{ backgroundColor: policyColor[name] }}
                    />
                    {name}
                  </td>
                  <td className="py-2 pr-4 text-right">{formatInr(s.recovered_inr)}</td>
                  <td className="py-2 pr-4 text-right">{formatNumber(s.retry_count, 0)}</td>
                  <td className="py-2 pr-4 text-right">{s.cost_per_inr_recovered.toFixed(4)}</td>
                  <td className="py-2 pr-4 text-right">{formatNumber(s.customer_contacts, 0)}</td>
                  <td className="py-2 pr-4 text-right">{s.double_charge_near_misses}</td>
                </tr>
              )
            })}
        </tbody>
      </table>
    </div>
  )
}
