import { expect, test } from '@playwright/test'

import { api, categoryId, makeLocation, unique } from './helpers'

test('create resistor with SI value and find it', async ({ page }) => {
  const drawer = unique('Drawer')
  await page.goto('/')
  await makeLocation(page, drawer)
  const name = unique('Resistor 4k7')
  await page.goto('/items/new')
  await page.getByTestId('category').selectOption({ label: 'Electronics › Passives › Resistors' })
  await page.getByTestId('name').fill(name)
  const resistance = page.getByTestId('field-resistance').locator('input')
  await resistance.fill('4k7')
  await resistance.blur()
  await page.getByTestId('field-package').locator('select').selectOption('0805')
  await page.getByTestId('quantity').fill('100')
  await page.getByTestId('initial-location').click()
  await page.getByText(drawer).click()
  await page.getByTestId('save-item').click()

  await expect(page.getByRole('heading', { name })).toBeVisible()
  await expect(page.getByText('4.7kΩ')).toBeVisible()
  await expect(page.getByTestId('on-hand')).toHaveText('On hand: 100')

  await page.goto('/search?q=4.7k')
  await expect(page.getByTestId('results')).toContainText(name)
})

test('create cell unit and log a capacity test', async ({ page }) => {
  await page.goto('/')
  const cells = await categoryId(page, 'Li-ion Cells')
  const item = await api<{ id: number; sku: string }>(page, 'POST', '/items', {
    category_id: cells,
    name: unique('Samsung 30Q'),
    attrs: { format: '18650', model: '30Q' },
  })
  expect(item.sku).toMatch(/^CELL-18650-30Q/)
  await page.goto(`/items/${item.id}`)
  await page.getByTestId('add-unit').click()
  await page.getByTestId('save-unit').click()
  const unitLink = page.getByTestId('units-table').getByRole('link').first()
  await expect(unitLink).toHaveText(/^C\d{4}$/)
  await unitLink.click()

  await page.getByTestId('add-capacity_test').click()
  for (const [key, value] of [['capacity_mah', '2950'], ['ir_mohm', '22'], ['storage_v', '3.70']]) {
    const input = page.getByTestId(`field-${key}`).locator('input')
    await input.fill(value)
    await input.blur()
  }
  await page.getByTestId('save-entry').click()
  await expect(page.getByTestId('latest-capacity_test')).toContainText('22mΩ')
  await expect(page.getByTestId('log-table')).toContainText('2950mAh')
})
