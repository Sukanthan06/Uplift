// Validated categorical/sequential/status palette (see dataviz skill,
// references/palette.md). Fixed order -- never cycled or reassigned per
// filter. Light-mode values only; this dashboard doesn't ship dark mode.

export const categorical = {
  blue: '#2a78d6',
  orange: '#eb6834',
  aqua: '#1baf7a',
  yellow: '#eda100',
  magenta: '#e87ba4',
  green: '#008300',
  violet: '#4a3aa7',
  red: '#e34948',
} as const

// Fixed policy -> color assignment, consistent across every chart on the
// page so a policy's color never changes meaning between sections.
export const policyColor: Record<string, string> = {
  do_nothing: categorical.blue,
  retry_once: categorical.orange,
  retry_3x: categorical.aqua,
  rule_based: categorical.yellow,
  uplift_ranked: categorical.magenta,
}

export const status = {
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
} as const

export const diverging = {
  positive: categorical.blue,
  negative: categorical.red,
  midpoint: '#f0efec',
}

export const ink = {
  primary: '#0b0b0b',
  secondary: '#52514e',
  muted: '#898781',
  gridline: '#e1e0d9',
  baseline: '#c3c2b7',
}

export const sequentialBlue = [
  '#cde2fb',
  '#9ec5f4',
  '#6da7ec',
  '#3987e5',
  '#256abf',
  '#184f95',
  '#0d366b',
]
