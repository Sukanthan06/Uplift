import { useState } from 'react'
import Overview from './pages/Overview'
import BatchRun from './pages/BatchRun'
import DecisionDetail from './pages/DecisionDetail'
import AuditVerify from './pages/AuditVerify'

const TABS = [
  { id: 'overview', label: 'Overview', component: Overview },
  { id: 'batch', label: 'Batch Run', component: BatchRun },
  { id: 'decision', label: 'Decision Detail', component: DecisionDetail },
  { id: 'audit', label: 'Audit Verify', component: AuditVerify },
] as const

type TabId = (typeof TABS)[number]['id']

export default function App() {
  const [active, setActive] = useState<TabId>('overview')
  const ActiveComponent = TABS.find((t) => t.id === active)!.component

  return (
    <div className="min-h-screen bg-gray-50 md:flex">
      <aside className="border-b border-gray-200 bg-white md:w-60 md:shrink-0 md:border-b-0 md:border-r">
        <div className="px-6 py-5">
          <h1 className="text-base font-semibold text-gray-900">Uplift</h1>
          <p className="mt-0.5 text-xs text-gray-500">Payment Recovery</p>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:overflow-visible md:px-3">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActive(tab.id)}
              className={`shrink-0 rounded-md px-3 py-2 text-left text-sm font-medium transition-colors md:shrink ${
                active === tab.id
                  ? 'bg-gray-900 text-white'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 flex-1 px-6 py-6 md:px-8">
        <div className="mx-auto max-w-[1200px]">
          <ActiveComponent />
        </div>
      </main>
    </div>
  )
}
