// When to stop waiting on the intake workflow. A request normally leaves pending/processing within seconds;
// one still there after STUCK_AFTER_MS is shown as stuck and stops the page from polling (the PM sees it in
// AI Ops queue health). Fresh requests keep the page polling.

export const STUCK_AFTER_MS = 2 * 60 * 1000

type Row = { id: number; status: string; created_at: string }

const IN_FLIGHT = new Set(['pending', 'processing'])

/** Server timestamps may come without a timezone; they are UTC. */
function utc(iso: string): number {
  return Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)
}

export function progress(rows: Row[], now: number): { poll: boolean; stuck: Set<number> } {
  const stuck = new Set<number>()
  let poll = false
  for (const r of rows) {
    if (!IN_FLIGHT.has(r.status)) continue
    if (now - utc(r.created_at) > STUCK_AFTER_MS) stuck.add(r.id)
    else poll = true
  }
  return { poll, stuck }
}
