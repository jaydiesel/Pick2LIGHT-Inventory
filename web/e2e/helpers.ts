import { expect, type Page } from '@playwright/test'

export const PASSWORD = 'correct horse battery'

/** Type a code like a barcode scanner: fast keystrokes, then Enter. */
export async function scan(page: Page, code: string, gapMs = 5): Promise<void> {
  await page.keyboard.type(code, { delay: gapMs })
  await page.keyboard.press('Enter')
}

export async function api<T = unknown>(page: Page, method: string, path: string, data?: unknown): Promise<T> {
  const res = await page.request.fetch(`/api/v1${path}`, { method, data })
  expect(res.ok(), `${method} ${path} → ${res.status()} ${await res.text()}`).toBeTruthy()
  return (res.status() === 204 ? undefined : await res.json()) as T
}

export async function categoryId(page: Page, name: string): Promise<number> {
  const cats = await api<{ id: number; name: string }[]>(page, 'GET', '/categories')
  const cat = cats.find((c) => c.name === name)
  expect(cat, `category ${name}`).toBeTruthy()
  return cat!.id
}

export async function makeLocation(page: Page, name: string): Promise<{ id: number; code: string }> {
  return api(page, 'POST', '/locations', { name })
}

export function unique(prefix: string): string {
  return `${prefix} ${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`
}
