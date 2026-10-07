// GP1 (test-plan §4; spec F0, F1; R8, R9): discover an existing need while typing, and support it instead of
// filing a duplicate.
import { expect, test } from '@playwright/test'

import { actAsRequester } from './support.ts'

test('a requester finds the SSO need while typing and adds support with a severity', async ({ page }) => {
  await actAsRequester(page, 'Kai Nakamura')
  await page.getByRole('link', { name: 'Submit a request' }).click()
  await expect(page.getByRole('heading', { name: 'Submit a request' })).toBeVisible()

  // Before anything is submitted: the closest existing needs, phrased as a problem for a persona
  // (offline similarity 0.809 to the SSO need; the next is 0.680).
  await page.getByLabel('Title').fill('Can we log in with Okta?')
  const matches = page.getByRole('list', { name: 'Existing needs that may match' })
  await expect(matches.getByRole('listitem').first()).toContainText('SSO') // the closest match
  const sso = matches.getByRole('listitem').filter({ hasText: 'SSO' }).first()
  await expect(sso).toContainText(/\bneeds\b/) // "IT director needs SAML SSO with Okta ...", not "Okta login"

  // Support it, with why it matters and a severity.
  await sso.getByRole('button', { name: 'This is my need' }).click()
  const dialog = page.getByRole('dialog', { name: 'Add your support' })
  await dialog.getByLabel('Why it matters to you').fill('Our team signs in to every other tool with Okta.')
  await dialog.getByRole('combobox', { name: 'Severity' }).click()
  await page.getByRole('option', { name: 'Blocker' }).click()
  await dialog.getByRole('button', { name: 'Add support' }).click()

  // A confirmation that stays on the page (the match list follows the title, so it can't hold the link).
  const done = page.getByTestId('support-confirmation')
  await expect(done).toContainText('Support added')

  // The need lists the support with its severity, and says whether it counts yet: a claim is checked first.
  // Offline, this reason is only 0.584 similar to the need (below the 0.651 suggest band), so the baseline
  // disputes it and a PM decides; with a model it can be confirmed.
  await done.getByRole('link', { name: 'View need' }).click()
  const supporters = page.getByRole('region', { name: 'Supporters' })
  const mine = supporters.getByRole('listitem').filter({ hasText: 'Kai Nakamura' })
  await expect(mine).toContainText('Blocker')
  await expect(mine).toContainText(/Waiting for confirmation|Confirmed|Disputed/)

  // Supporting didn't file a duplicate request.
  await page.getByRole('link', { name: 'My requests' }).click()
  await expect(page.getByRole('table', { name: 'My requests' })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'Can we log in with Okta?' })).toHaveCount(0)
})
