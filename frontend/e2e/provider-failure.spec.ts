// GP6 (test-plan §4; spec F2 failure path; CLAUDE.md rule 2: AI never blocks a submission). The provider fails
// (a test-only switch, active only with APP_ENV=test, triggered by a marker in the text): the request is
// still saved, the requester sees a plain reason, and the PM finds it in Needs review with the real one.
import { expect, test } from '@playwright/test'

import { actAsPM, actAsRequester, toasts } from './support.ts'

const MARKER = '[simulate-provider-failure]'

test('a request whose AI step fails is saved and lands in the PM’s Needs review with the reason', async ({ page }) => {
  await actAsRequester(page, 'Rosa Bianchi')
  await page.getByRole('link', { name: 'Submit a request' }).click()
  await page.getByLabel('Title').fill('Inventory forecasting')
  await page.getByLabel('Description').fill(`Forecast how much flour to order each week ${MARKER}`)
  await page.getByRole('button', { name: 'Submit as a new request' }).click()
  await expect(toasts(page).getByText('Request submitted')).toBeVisible() // saved before any model call

  // The requester sees where it stands, in plain words, never the internal error.
  await page.getByRole('link', { name: 'My requests' }).click()
  const row = page.getByRole('table', { name: 'My requests' }).getByRole('row').filter({ hasText: 'Inventory forecasting' })
  await expect(row.getByTestId('request-status')).toHaveText('Needs review', { timeout: 30_000 })
  await expect(row).toContainText('a PM will review it')
  await expect(row).not.toContainText('simulated provider failure')

  // The PM finds it in Needs review, with the reason the AI step failed.
  await actAsPM(page)
  await page.getByRole('link', { name: 'Triage inbox' }).click()
  await page.getByRole('tab', { name: /Needs review/ }).click()
  const failed = page.getByRole('list', { name: 'Requests that need review' }).getByRole('listitem').filter({ hasText: 'Inventory forecasting' })
  await expect(failed).toContainText('simulated provider failure')
  await expect(failed).toContainText('1 attempt')
})
