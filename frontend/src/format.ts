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

const TIMESTAMP_PARTS = new Intl.DateTimeFormat('en-US', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
  timeZone: 'Asia/Kolkata',
})

// "30 Aug 2026, 11:04 PM IST". Built from formatToParts rather than a
// single Intl.format() call because en-IN renders "Sept"/lowercase
// "am"/"pm" -- neither matches this exact target style, and there's no
// hour12 casing option to fix the latter directly.
export function formatTimestamp(value: string | Date): string {
  const date = typeof value === 'string' ? new Date(value) : value
  const parts = Object.fromEntries(
    TIMESTAMP_PARTS.formatToParts(date).map((p) => [p.type, p.value])
  )
  return `${parts.day} ${parts.month} ${parts.year}, ${parts.hour}:${parts.minute} ${parts.dayPeriod.toUpperCase()} IST`
}
