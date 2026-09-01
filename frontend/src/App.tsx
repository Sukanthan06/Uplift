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
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto max-w-6xl px-6 py-4">
          <h1 className="text-lg font-semibold text-gray-900">Uplift</h1>
          <p className="text-xs text-gray-500">Intelligent Payment Recovery</p>
        </div>
        <nav className="mx-auto flex max-w-6xl gap-1 px-6">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActive(tab.id)}
              className={`border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                active === tab.id
                  ? 'border-gray-900 text-gray-900'
                  : 'border-transparent text-gray-500 hover:text-gray-800'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-6">
        <ActiveComponent />
      </main>
    </div>
  )
}
