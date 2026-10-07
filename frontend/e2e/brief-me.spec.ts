// GP7 (test-plan §4; spec F6, ADR 0012): "Brief me". The PM asks for a decision brief; the worker runs the
// bounded related-needs agent and one brief call, code verifies every claim, and the page shows how it was built.
// Offline the agent step is the embedding baseline and the brief a template, labelled as such.
import { expect, test } from '@playwright/test'

import { AI_MODE } from '../playwright.config.ts'
import { actAsPM } from './support.ts'

const LIVE = AI_MODE === 'live'

test('the PM asks for a brief and sees it verified, with the steps that built it', async ({ page }) => {
  await actAsPM(page)
  await page.getByRole('link', { name: 'Browse needs' }).click()
  await page.getByLabel('Search needs').fill('SAML SSO with Okta')
  await page.getByRole('link', { name: /SAML SSO with Okta/ }).first().click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('SAML SSO with Okta')

  const section = page.getByRole('region', { name: 'Decision brief' })
  await section.getByRole('button', { name: 'Brief me' }).click()

  // The worker builds it in the background; the page polls until it is ready.
  const brief = section.getByRole('article', { name: 'Decision brief' })
  await expect(brief).toBeVisible({ timeout: LIVE ? 150_000 : 30_000 }) // live: up to 9 agent turns and a Sonnet call
  await expect(brief.getByTestId('brief-source')).toContainText(LIVE ? 'Sonnet' : 'Offline baseline')
  await expect(brief.getByRole('heading', { name: 'Summary' })).toBeVisible()
  await expect(brief.getByRole('heading', { name: 'Recommendation' })).toBeVisible()

  // Figures come from the data: each impact claim shows the values it cites.
  await expect(brief.getByTestId('impact-fact').filter({ hasText: '$' }).first()).toBeVisible()

  // Every quote is checked against its request; the verification line says how many claims held.
  await expect(brief.getByRole('blockquote').first()).toBeVisible()
  // offline the template always verifies; live, flagged claims are allowed but must be counted and shown
  await expect(brief.getByTestId('brief-verification')).toContainText(LIVE ? /claims (checked|unverified)/ : /All \d+ claims checked/)

  // How this brief was built: the agent's steps, bounded by the cap, and every model call with its cost.
  await brief.getByRole('button', { name: 'How this brief was built' }).click()
  const how = brief.getByRole('region', { name: 'How this brief was built' })
  await expect(how.getByText(/of 8 tool calls/)).toBeVisible()
  const steps = how.getByRole('table', { name: 'Agent steps' })
  await expect(steps.getByRole('row').nth(1)).toContainText('search_needs')
  const calls = how.getByRole('table', { name: 'Model calls' })
  await expect(calls.getByRole('row', { name: /decision_brief/ })).toBeVisible()

  // AI Ops shows the same calls from ai_runs: tokens, cost and latency per step.
  await page.getByRole('link', { name: 'AI Ops' }).click()
  const ops = page.getByRole('table', { name: 'Model calls' })
  const row = ops.getByRole('row').filter({ hasText: 'Decision brief' }).filter({ hasText: LIVE ? 'Sonnet' : 'Offline baseline' })
  await expect(row).toBeVisible()
  if (LIVE) await expect(row).toContainText(/[1-9][\d,]* \/ [1-9][\d,]*/) // real tokens in and out
})
