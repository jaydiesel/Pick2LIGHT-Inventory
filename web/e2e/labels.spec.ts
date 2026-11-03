import { expect, test } from '@playwright/test'

import { api, categoryId, unique } from './helpers'

test('print unit label returns pdf', async ({ page }) => {
  await page.goto('/')
  const cells = await categoryId(page, 'Li-ion Cells')
  const item = await api<{ id: number }>(page, 'POST', '/items', { category_id: cells, name: unique('Molicel P42A') })
  const unit = await api<{ id: number }>(page, 'POST', '/units', { item_id: item.id })
  await page.goto(`/units/${unit.id}`)
  const response = page.waitForResponse((r) => r.url().endsWith('/api/v1/labels/pdf'))
  await page.getByRole('button', { name: 'Print label' }).click()
  const res = await response
  expect(res.status()).toBe(200)
  expect(res.headers()['content-type']).toBe('application/pdf')
  // The page hands the blob to a new tab, so fetch the same request again to check the bytes.
  const again = await page.request.post('/api/v1/labels/pdf', { data: res.request().postDataJSON() })
  expect((await again.body()).subarray(0, 4).toString()).toBe('%PDF')
})
