import { expect, test } from '@playwright/test'

import { api, categoryId, makeLocation, scan, unique } from './helpers'

test('scan unit code opens unit page', async ({ page }) => {
  await page.goto('/')
  const cells = await categoryId(page, 'Li-ion Cells')
  const item = await api<{ id: number }>(page, 'POST', '/items', { category_id: cells, name: unique('LG MJ1') })
  const unit = await api<{ id: number; unit_code: string }>(page, 'POST', '/units', { item_id: item.id })
  await page.goto('/')
  await scan(page, unit.unit_code)
  await expect(page).toHaveURL(new RegExp(`/units/${unit.id}$`))
  await expect(page.getByRole('heading', { name: unit.unit_code })).toBeVisible()
})

test('check-out mode scan decrements stock', async ({ page }) => {
  await page.goto('/')
  const screws = await categoryId(page, 'Screws & Bolts')
  const loc = await makeLocation(page, unique('Screw drawer'))
  const item = await api<{ id: number; sku: string }>(page, 'POST', '/items', {
    category_id: screws,
    name: unique('M3x10 SHCS'),
    sku: unique('E2E-SCR').replace(/\s/g, '-'),
  })
  await api(page, 'POST', '/stock/add', { item_id: item.id, location_id: loc.id, quantity: 100 })
  await page.goto('/')
  await page.getByTestId('mode-check_out').click()
  await page.getByTestId('quantity').fill('5')
  await page.locator('body').click()
  await scan(page, item.sku)
  await expect(page.getByTestId('recent-scans')).toContainText(/Checked out 5 ×/)
  await page.goto(`/items/${item.id}`)
  await expect(page.getByTestId('on-hand')).toHaveText('On hand: 95')
})

test('unknown scan offers create', async ({ page }) => {
  await page.goto('/')
  const code = `400${Date.now()}`.slice(0, 13)
  await scan(page, code)
  await expect(page.getByTestId('recent-scans')).toContainText(`Unknown code ${code}`)
  await page.reload()
  await expect(page.getByTestId('unknown-scans')).toContainText(code)
  await page.getByTestId('unknown-scans').getByRole('link', { name: 'Create item' }).first().click()
  await expect(page).toHaveURL(/\/items\/new\?barcode=/)
})

test('slow typing in search box is not treated as a scan', async ({ page }) => {
  await page.goto('/')
  const box = page.getByRole('search').first().locator('input')
  await box.click()
  await page.keyboard.type('abcd', { delay: 150 })
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/search\?q=abcd$/)
})
