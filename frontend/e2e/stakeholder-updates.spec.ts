// GP5 (test-plan §4; spec F7, M3): closing the loop. The AI drafts, code flags commitments the PM didn't
// make, the PM fixes and approves, and only then does the requester see anything.
import { expect, test } from '@playwright/test'

import { actAsPM, actAsRequester, toasts } from './support.ts'

const CLEAN = 'Thanks for asking about single sign-on. We have marked it as planned because enterprise rollouts depend on it.'
const FOR_PRIYA = 'Hi Priya, your SAML SSO with Okta request is now planned: enterprise rollouts depend on it.'
const CS_NOTE = 'Internal: SSO is planned; tell Northwind it is on the roadmap without a date.'

test('the PM marks SSO planned, fixes a flagged commitment, approves, and the requester sees the update', async ({ page }) => {
  await actAsPM(page)
  await page.getByRole('link', { name: 'Browse needs' }).click()
  await page.getByLabel('Search needs').fill('SAML SSO with Okta')
  await page.getByRole('link', { name: /SAML SSO with Okta/ }).first().click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('SAML SSO with Okta')
  const needUrl = page.url()

  // The decision: a reason with a vague timeframe, and no date the PM commits to.
  await page.getByRole('button', { name: 'Change status' }).click()
  const dialog = page.getByRole('dialog', { name: 'Change status' })
  await dialog.getByRole('combobox', { name: 'New status' }).click()
  await page.getByRole('option', { name: 'Planned' }).click()
  await dialog.getByLabel('Reason').fill('Enterprise rollouts depend on it, so it is going into next quarter')
  await dialog.getByRole('button', { name: 'Save status' }).click()
  await expect(toasts(page).getByText(/Status set to Planned/)).toBeVisible()

  // The worker drafts one personal update per supporter (offline: a template with the PM's reason).
  const updates = page.getByRole('region', { name: 'Stakeholder updates' })
  const drafts = updates.getByTestId('requester-update')
  await expect(drafts.first()).toBeVisible({ timeout: 30_000 })
  const total = await drafts.count()
  await expect(updates.getByText(`0 of ${total} supporters notified`)).toBeVisible() // nothing went out on its own

  // Priya's draft refers to what she asked for, and the commitment check caught "next quarter".
  const priya = updates.getByRole('article', { name: 'Update to Priya Raman' })
  await expect(priya.getByRole('textbox')).toHaveValue(/SAML SSO with Okta/)
  await expect(priya.getByRole('status', { name: 'Flagged commitments' })).toContainText('next quarter')
  await expect(priya.getByRole('button', { name: 'Approve and send' })).toBeDisabled()

  // The PM fixes every personal draft, saves (the check runs again) and approves.
  for (let i = 0; i < total; i++) {
    const draft = drafts.nth(i)
    const isPriya = (await draft.getAttribute('aria-label')) === 'Update to Priya Raman'
    await draft.getByRole('textbox').fill(isPriya ? FOR_PRIYA : CLEAN)
    await draft.getByRole('button', { name: 'Save changes' }).click()
    await expect(draft.getByRole('status', { name: 'Flagged commitments' })).toHaveCount(0)
    await draft.getByRole('button', { name: 'Approve and send' }).click()
    await expect(draft).toContainText('in the outbox')
  }
  await expect(updates.getByText(`${total} of ${total} supporters notified`)).toBeVisible()

  // One internal CS note goes out too; it must never reach a requester.
  const note = updates.getByRole('article', { name: 'CS note for Northwind Logistics' })
  await note.getByRole('textbox').fill(CS_NOTE)
  await note.getByRole('button', { name: 'Save changes' }).click()
  await note.getByRole('button', { name: 'Approve and send' }).click()
  await expect(note).toContainText('in the outbox')

  // AI Ops: decision-loop latency is now measured from these timestamps.
  await page.getByRole('link', { name: 'AI Ops' }).click()
  const m3 = page.getByRole('group', { name: 'M3 · Decision-loop latency' })
  await expect(m3).not.toContainText('Not measured yet')
  await expect(m3).toContainText(/\d+(\.\d)? (s|min|h|days)/)
  await expect(m3).toContainText('1 decision with every supporter notified')

  // The requester sees the approved update on the need's page.
  await actAsRequester(page, 'Priya Raman')
  await page.goto(needUrl)
  const mine = page.getByRole('region', { name: 'Updates' })
  await expect(mine.getByRole('listitem')).toHaveCount(1) // her own update only
  await expect(mine).toContainText(FOR_PRIYA)
  await expect(mine).not.toContainText(CS_NOTE)
  await expect(mine).not.toContainText(CLEAN)
})
