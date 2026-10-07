// GP3 (test-plan §4; spec F3, F5; Q6): the PM works the inbox: accept a suggestion, check an audited
// auto-link, undo an auto-link.
import { expect, test } from '@playwright/test'

import { AI_MODE } from '../playwright.config.ts'

import { actAsPM, API, requesterId, toasts } from './support.ts'

test('the PM accepts a suggestion, checks an audited auto-link and undoes an auto-link', async ({ page, request }) => {
  // A request the offline baseline places in the gray zone: similarity 0.735 to the SSO need, between the
  // suggest (0.651) and auto (0.767) thresholds, so it becomes a suggestion for the PM, not a link.
  const created = await request.post(`${API}/requests`, {
    data: {
      requester_id: await requesterId(request, 'Femi Adeyemi'),
      title: 'Okta',
      description: 'Sign in with Okta would help our team',
      source: 'portal',
    },
  })
  expect(created.status()).toBe(201)

  await actAsPM(page)
  await page.getByRole('link', { name: 'Triage inbox' }).click()
  await expect(page.getByRole('heading', { name: 'Triage inbox' })).toBeVisible()

  // Live, Haiku judges the same text: it may be same_need above T_auto (auto-linked, labelled, undoable) or a
  // gray-zone suggestion. Either way it must land on the SSO need, never on another one.
  if (AI_MODE === 'live') {
    await test.step('the live adjudicator routes the Okta request to SSO', async () => {
      const text = 'Sign in with Okta would help our team'
      const femi = await requesterId(request, 'Femi Adeyemi')
      await expect
        .poll(async () => {
          const mine = (await (await request.get(`${API}/requests?requester_id=${femi}`)).json()) as { title: string; status: string }[]
          return mine.find((r) => r.title === 'Okta')?.status
        }, { timeout: 60_000 })
        .toBe('processed') // the worker has routed it; now see where it went
      const suggestion = page.getByRole('tabpanel').getByRole('article').filter({ hasText: text })
      await page.getByRole('tab', { name: /Suggestions/ }).click()
      const suggested = await suggestion.waitFor({ timeout: 8_000 }).then(() => true, () => false) // the inbox polls every 3 s
      if (suggested) {
        await expect(suggestion).toContainText('SSO')
        await expect(suggestion.getByTestId('routing-badge')).toContainText('Haiku')
        await suggestion.getByRole('button', { name: 'Accept' }).click()
        await expect(toasts(page).getByText(/^Linked to/)).toBeVisible()
      } else {
        await page.getByRole('tab', { name: /Auto-linked/ }).click()
        const linked = page.getByRole('tabpanel').getByRole('article').filter({ hasText: text })
        await expect(linked).toBeVisible({ timeout: 30_000 })
        await expect(linked).toContainText('SSO')
        await expect(linked.getByTestId('routing-badge')).toContainText('Haiku')
      }
    })
  } else await test.step('accept a suggestion', async () => {
    await page.getByRole('tab', { name: /Suggestions/ }).click()
    const item = page.getByRole('article').filter({ hasText: 'Sign in with Okta would help our team' })
    await expect(item).toBeVisible({ timeout: 30_000 }) // the worker processes it; the inbox polls
    await expect(item).toContainText('SSO') // shown next to the need it would join
    const badge = item.getByTestId('routing-badge')
    await expect(badge).toContainText('Offline baseline')
    await badge.getByRole('button', { name: /^Why\?/ }).hover()
    await expect(page.getByRole('tooltip')).toContainText(/similar/i)
    await page.keyboard.press('Escape') // close the tooltip so it can't cover the buttons
    await item.getByRole('button', { name: 'Accept' }).click()
    await expect(item).toBeHidden()
    await expect(toasts(page).getByText(/^Linked to/)).toBeVisible()
  })

  await test.step('check an auto-link from the audit sample', async () => {
    await page.getByRole('tab', { name: /Audit sample/ }).click()
    const items = page.getByRole('tabpanel').getByRole('article')
    await expect(items.first()).toBeVisible() // the seed's 10% sample of auto-links (3 items)
    const before = await items.count()
    const first = items.first()
    await expect(first.getByTestId('routing-badge')).toBeVisible()
    await first.getByRole('button', { name: 'Correct' }).click()
    await expect(items).toHaveCount(before - 1)
  })

  await test.step('undo an auto-link', async () => {
    await page.getByRole('tab', { name: /Auto-linked/ }).click()
    const first = page.getByRole('tabpanel').getByRole('article').first()
    await expect(first).toBeVisible()
    const requestId = await first.getAttribute('data-request-id')
    expect(requestId).toMatch(/^\d+$/)
    await first.getByRole('button', { name: 'Undo' }).click()
    await page.getByRole('alertdialog', { name: 'Undo this link?' }).getByRole('button', { name: 'Undo link' }).click()
    await expect(toasts(page).getByText(/now its own need/)).toBeVisible()
    await expect(page.getByRole('tabpanel').locator(`article[data-request-id="${requestId}"]`)).toHaveCount(0)
  })
})
