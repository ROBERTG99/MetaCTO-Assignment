// Display labels and formatters shared by both halves of the UI. One wording per concept, everywhere.

/** "claude-haiku-4-5-20251001" -> "Haiku 4.5"; the offline path says so plainly. */
export function sourceLabel(model: string | null | undefined): string {
  if (!model) return 'AI'
  if (model.startsWith('offline')) return 'Offline baseline'
  const m = /^claude-([a-z]+)-(\d+)-(\d+)/.exec(model)
  if (!m) return model
  const [, family = '', major, minor] = m
  return `${family.charAt(0).toUpperCase()}${family.slice(1)} ${major}.${minor}`
}

export const REQUEST_STATUS: Record<string, string> = {
  pending: 'Pending',
  processing: 'Processing',
  processed: 'Processed',
  needs_review: 'Needs review',
}

export const NEED_STATUS: Record<string, string> = {
  open: 'Open',
  planned: 'Planned',
  in_progress: 'In progress',
  shipped: 'Shipped',
  declined: 'Declined',
  merged: 'Merged',
}

export const SEVERITY: Record<string, string> = {
  blocker: 'Blocker',
  important: 'Important',
  nice_to_have: 'Nice to have',
  unknown: 'No severity',
}

/** A support's link status, in the requester's words. */
export const SUPPORT_STATUS: Record<string, string> = {
  claimed: 'Waiting for confirmation',
  confirmed: 'Confirmed',
  disputed: 'Disputed',
  rejected: 'Not counted',
}

export const SEGMENT: Record<string, string> = {
  enterprise: 'Enterprise',
  mid_market: 'Mid-market',
  smb: 'SMB',
}

export const QUADRANT: Record<string, string> = {
  clear_win: 'Clear wins',
  strategic_bet: 'Strategic bets',
  popular_off_strategy: 'Popular but off-strategy',
  park: 'Park',
}

/** snake_case codes from the model or config (it_admin, security_admin) as words. */
const ACRONYMS: Record<string, string> = { it: 'IT', ui: 'UI', smb: 'SMB', pm: 'PM', bi: 'BI', cs: 'CS', sso: 'SSO' }

export function humanize(code: string | null | undefined): string {
  if (!code) return '—'
  const words = code.split('_').map((w) => ACRONYMS[w] ?? w)
  const text = words.join(' ')
  return ACRONYMS[words[0] ?? ''] ? text : text.charAt(0).toUpperCase() + text.slice(1)
}

export function money(usd: number | null | undefined): string {
  if (usd == null) return '—'
  if (Math.abs(usd) >= 1_000_000) return `$${(usd / 1_000_000).toFixed(1)}M`
  if (Math.abs(usd) >= 1_000) return `$${Math.round(usd / 1_000)}k`
  return `$${Math.round(usd)}`
}

/** API cost in dollars: small numbers keep their precision ($0.0042). */
export function cost(usd: number | null | undefined): string {
  if (usd == null) return '—'
  return usd < 1 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`
}

export function percent(x: number | null | undefined, digits = 0): string {
  return x == null ? '—' : `${(x * 100).toFixed(digits)}%`
}

/** Scores in 0-1 (routing, similarity, D, S, U): two decimals. Priority points: one decimal. */
export const score = (x: number | null | undefined) => (x == null ? '—' : x.toFixed(2))
export const points = (x: number | null | undefined) => (x == null ? '—' : x.toFixed(1))

export function when(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}
