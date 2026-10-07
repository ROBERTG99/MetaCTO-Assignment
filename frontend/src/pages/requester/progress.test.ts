import { describe, expect, it } from 'vitest'

import { STUCK_AFTER_MS, progress } from './progress'

const now = Date.parse('2026-10-07T12:00:00Z')
const at = (msAgo: number) => new Date(now - msAgo).toISOString()

describe('progress of my requests', () => {
  it('polls while a recent request is still waiting for the intake workflow', () => {
    const p = progress([{ id: 1, status: 'pending', created_at: at(5_000) }], now)
    expect(p.poll).toBe(true)
    expect(p.stuck.size).toBe(0)
  })

  it('stops polling and marks a request stuck once it has waited past the timeout', () => {
    const p = progress(
      [
        { id: 1, status: 'processing', created_at: at(STUCK_AFTER_MS + 1) },
        { id: 2, status: 'processed', created_at: at(10_000) },
      ],
      now,
    )
    expect(p.poll).toBe(false)
    expect([...p.stuck]).toEqual([1])
  })

  it('keeps polling for a fresh request even when an older one is stuck', () => {
    const p = progress(
      [
        { id: 1, status: 'pending', created_at: at(STUCK_AFTER_MS * 3) },
        { id: 2, status: 'pending', created_at: at(1_000) },
      ],
      now,
    )
    expect(p.poll).toBe(true)
    expect([...p.stuck]).toEqual([1])
  })

  it('reads server timestamps without a timezone as UTC', () => {
    const naive = new Date(now - STUCK_AFTER_MS - 1).toISOString().replace('Z', '')
    expect(progress([{ id: 1, status: 'pending', created_at: naive }], now).stuck.has(1)).toBe(true)
  })

  it('never polls when nothing is in flight', () => {
    expect(progress([{ id: 1, status: 'needs_review', created_at: at(1) }], now).poll).toBe(false)
  })
})
