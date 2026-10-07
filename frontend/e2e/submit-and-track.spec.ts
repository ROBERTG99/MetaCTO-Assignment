// GP2 (test-plan §4; spec F2; R7): submit a genuinely new request, then follow it to the need it was linked to.
import { expect, test } from '@playwright/test'

import { AI_MODE } from '../playwright.config.ts'

import { actAsRequester, toasts } from './support.ts'

test('a requester submits a new request and later sees its status and its need', async ({ page }) => {
  await actAsRequester(page, 'Lily Tran')
  await page.getByRole('link', { name: 'Submit a request' }).click()

  // Nothing in the backlog is about meeting rooms (offline similarity 0.613, below the 0.651 suggest band).
  await page.getByLabel('Title').fill('Book meeting rooms')
  await page.getByLabel('Description').fill('Let employees reserve meeting rooms')
  await page.getByRole('button', { name: 'Submit as a new request' }).click()
  await expect(toasts(page).getByText('Request submitted')).toBeVisible()

  // It is saved at once and processed in the background; the list polls, so it updates without a reload.
  await page.getByRole('link', { name: 'My requests' }).click()
  const row = page.getByRole('table', { name: 'My requests' }).getByRole('row').filter({ hasText: 'Book meeting rooms' })
  await expect(row).toBeVisible()
  await expect(row.getByTestId('request-status')).toHaveText('Processed', { timeout: 30_000 })

  // The need it was linked to: here a new one, created by the intake step, which says where it came from.
  await row.getByTestId('need-link').click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText(/meeting rooms/i)
  await expect(page.getByTestId('need-source')).toContainText(AI_MODE === 'live' ? 'Haiku' : 'Offline baseline')
  await expect(page.getByRole('region', { name: 'Requests' })).toContainText('Lily Tran')
})
