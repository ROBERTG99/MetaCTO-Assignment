// GP4 (test-plan §4; spec F4, §8; R10): popular vs strategic, and a score whose every component is explained.
import { expect, test } from '@playwright/test'

import { actAsPM } from './support.ts'

test('the PM sees the quadrant and opens a breakdown that explains each component', async ({ page }) => {
  await actAsPM(page)
  await page.getByRole('link', { name: 'Priorities' }).click()
  await expect(page.getByRole('heading', { name: 'Priorities' })).toBeVisible()

  // Popular (revenue-weighted demand) and strategic (goal fit) stay separate.
  const quadrant = page.getByRole('region', { name: 'Popular vs strategic' })
  for (const name of ['Clear wins', 'Strategic bets', 'Popular but off-strategy', 'Park', 'Not rated yet']) {
    await expect(quadrant.getByRole('heading', { name })).toBeVisible()
  }
  await expect(quadrant.getByText(/SAML SSO with Okta/)).toBeVisible() // every undecided need is placed

  // The ranked list, and the breakdown behind one score.
  const row = page.getByRole('table', { name: 'Needs by priority' }).getByRole('row').filter({ hasText: /SAML SSO with Okta/ })
  const shown = Number((await row.getByTestId('priority').textContent())?.trim())
  expect(Number.isFinite(shown)).toBe(true)
  await row.getByRole('button', { name: 'Explain score' }).click()
  const panel = page.getByRole('dialog', { name: /Score breakdown/ })

  const demand = panel.getByRole('region', { name: 'Demand' })
  await expect(demand).toContainText(/\d+ accounts?/)
  await expect(demand).toContainText(/\$\d/) // the revenue behind it
  const urgency = panel.getByRole('region', { name: 'Urgency' })
  await expect(urgency).toContainText(/Blocker|Important|Nice to have|No severity/)
  await expect(urgency).toContainText(/renew/i)
  // Offline the seed has no recorded fit ratings (fit_snapshot.json needs the paid run), so SSO is not rated or
  // pending; with ratings it shows each goal. Either way the section says which.
  const strategic = panel.getByRole('region', { name: 'Strategic fit' })
  await expect(strategic).toContainText(/Enterprise readiness|Not rated|Pending/)

  // The components' points (one decimal each; an unrated component shows none) add up to the score shown.
  const points = (await panel.getByTestId('points').allTextContents()).map((p) => Number.parseFloat(p))
  expect(points.length).toBeGreaterThanOrEqual(2)
  expect(points.every(Number.isFinite)).toBe(true)
  const sum = points.reduce((a, b) => a + b, 0)
  expect(Math.abs(sum - shown)).toBeLessThanOrEqual(0.05 * (points.length + 1) + 1e-9)
  await expect(panel.getByTestId('priority-total')).toHaveText(shown.toFixed(1))
})
