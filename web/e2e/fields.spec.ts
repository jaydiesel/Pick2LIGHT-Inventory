import { expect, test } from '@playwright/test'

import { api, unique } from './helpers'

test('item stays editable after one of its fields is removed', async ({ page }) => {
  await page.goto('/')
  const cat = await api<{ id: number }>(page, 'POST', '/categories', {
    name: unique('Paint'),
    fields: [
      { key: 'color', type: 'text' },
      { key: 'finish', type: 'text' },
    ],
  })
  const item = await api<{ id: number }>(page, 'POST', '/items', {
    category_id: cat.id,
    name: unique('Blue paint'),
    attrs: { color: 'blue', finish: 'matte' },
  })
  const fields = await api<{ id: number; key: string }[]>(page, 'GET', `/categories/${cat.id}/fields`)
  await api(page, 'DELETE', `/fields/${fields.find((f) => f.key === 'finish')!.id}`)

  await page.goto(`/items/${item.id}/edit`)
  const renamed = unique('Navy paint')
  await page.getByTestId('name').fill(renamed)
  await page.getByTestId('field-color').locator('input').fill('navy')
  await page.getByTestId('save-item').click()
  await expect(page.getByRole('heading', { name: renamed })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'navy', exact: true })).toBeVisible()
})
