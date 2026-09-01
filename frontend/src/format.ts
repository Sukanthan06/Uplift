export function formatInr(value: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(value)
}

export function formatNumber(value: number, digits = 1): string {
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: digits }).format(value)
}

export function formatPct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`
}
