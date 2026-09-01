export const API_BASE = 'http://localhost:8000'

export interface PolicyScore {
  recovered_inr: number
  retry_count: number
  cost_inr: number
  cost_per_inr_recovered: number
  customer_contacts: number
  double_charge_near_misses: number
}

export interface Phase3Result {
  n_test: number
  baselines: Record<string, PolicyScore>
  uplift_at_20pct: number
  qini_curve: [number, number][]
}

export interface SweepPoint {
  value: number
  recovered_inr: Record<string, number>
  margin_pct: number | null
}

export interface Sweep {
  label: string
  points: SweepPoint[]
}

export interface Heatmap {
  param_a: { name: string; label: string }
  param_b: { name: string; label: string }
  values_a: number[]
  values_b: number[]
  margins: (number | null)[][]
}

export interface Phase4Sweeps {
  sweeps: Record<string, Sweep>
  heatmap: Heatmap
}

export interface OverviewResponse {
  simulator: {
    total_attempts: number
    failed_attempts: number
    method_mix: Record<string, number>
  }
  phase2_baselines: Record<string, PolicyScore>
  phase3: Phase3Result | null
  phase4_sweeps: Phase4Sweeps | null
  pipeline_activity: {
    decisions_by_action: Record<string, number>
    actions_by_outcome: Record<string, number>
    audit_records: number
    audit_all_valid: boolean
  }
}

export async function fetchOverview(): Promise<OverviewResponse> {
  const res = await fetch(`${API_BASE}/overview`)
  if (!res.ok) throw new Error(`GET /overview failed: ${res.status}`)
  return res.json()
}

export interface DecisionSummary {
  decision_id: number
  order_id: string
  method: string
  error_code: string
  amount: number
  chosen_action: string
  rules_fired: string[]
  uplift_best: number
  created_at: string
}

export async function fetchDecisions(): Promise<DecisionSummary[]> {
  const res = await fetch(`${API_BASE}/decisions`)
  if (!res.ok) throw new Error(`GET /decisions failed: ${res.status}`)
  return res.json()
}

export interface DecisionDetail {
  decision_id: number
  order_id: string
  method: string
  error_code: string
  error_desc: string | null
  amount: number
  uplift_now: number
  uplift_best: number
  best_retry_time: string | null
  chosen_action: string
  policy_version: string
  rules_fired: string[]
  reconciliation: { gateway_reported_status: string; reconciled_at: string } | null
  diagnosis: {
    root_cause: string
    cause_family: string
    is_transient: boolean
    confidence: number
    created_at: string
  } | null
  action: {
    idempotency_key: string
    api_attempt_no: number
    http_status: number | null
    outcome: string
    created_at: string
  } | null
  audit_trail: { id: number; payload_json: Record<string, unknown>; created_at: string }[]
}

export async function fetchDecisionDetail(id: number): Promise<DecisionDetail> {
  const res = await fetch(`${API_BASE}/decisions/${id}`)
  if (!res.ok) throw new Error(`GET /decisions/${id} failed: ${res.status}`)
  return res.json()
}

export interface AuditVerifyResponse {
  total_records: number
  all_valid: boolean
  first_invalid_id: number | null
  records: { id: number; valid: boolean; reason: string | null }[]
}

export async function fetchAuditVerify(): Promise<AuditVerifyResponse> {
  const res = await fetch(`${API_BASE}/audit/verify`)
  if (!res.ok) throw new Error(`GET /audit/verify failed: ${res.status}`)
  return res.json()
}

export interface BatchAttemptEvent {
  index: number
  order_id: string
  method: string
  error_code: string
  cause_family: string
  chosen_action: string
  rules_fired: string[]
  uplift_best: number
  action_outcome: string | null
}
