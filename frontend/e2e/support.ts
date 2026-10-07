// Shared steps. The role switcher is the only "login" (spec A3): pick a role, and for requesters a person.
import { expect, type APIRequestContext, type Locator, type Page } from '@playwright/test'

import { API_URL } from '../playwright.config.ts'

export const API = API_URL

export async function actAsRequester(page: Page, name: string) {
  await page.goto('/')
  await chooseRole(page, 'Requester')
  await page.getByRole('combobox', { name: 'Acting as' }).click()
  await page.getByRole('option', { name: new RegExp(`^${name}`) }).click()
  await expect(page.getByRole('combobox', { name: 'Acting as' })).toContainText(name)
}

export async function actAsPM(page: Page) {
  await page.goto('/')
  await chooseRole(page, 'Product manager')
}

async function chooseRole(page: Page, role: 'Requester' | 'Product manager') {
  await page.getByRole('combobox', { name: 'Role' }).click()
  await page.getByRole('option', { name: role }).click()
  await expect(page.getByRole('combobox', { name: 'Role' })).toContainText(role)
}

/** The toast region (sonner labels it "Notifications"), so a toast's text never collides with page text. */
export function toasts(page: Page): Locator {
  return page.getByRole('region', { name: /^Notifications/ })
}

/** A seeded requester's id, looked up by name through the API. */
export async function requesterId(request: APIRequestContext, name: string): Promise<number> {
  const people = (await (await request.get(`${API}/requesters`)).json()) as { id: number; name: string }[]
  const person = people.find((p) => p.name === name)
  if (!person) throw new Error(`no seeded requester named ${name}`)
  return person.id
}
