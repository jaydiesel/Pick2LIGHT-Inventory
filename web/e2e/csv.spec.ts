import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

const here = path.dirname(fileURLToPath(import.meta.url))

test('import semicolon CSV with mapping', async ({ page }) => {
  await page.goto('/import-export')
  await page.getByTestId('import-category').selectOption({ label: 'Electronics › Passives › Resistors' })
  await page.getByTestId('import-file').setInputFiles(path.join(here, 'fixtures', 'parts.csv'))
  await expect(page.getByTestId('map-Resistance')).toHaveValue('attr.resistance')
  await page.getByTestId('preview-import').click()
  const table = page.getByTestId('preview-table')
  await expect(table.locator('tr.bad')).toHaveCount(1)
  await expect(page.getByTestId('apply-import')).toBeDisabled()
  await page.getByTestId('skip-invalid').check()
  await page.getByTestId('apply-import').click()
  await expect(page.getByRole('heading', { name: 'Imported' })).toBeVisible()
  await page.goto('/search?q=E2E%20Resistor')
  await expect(page.getByTestId('results')).toContainText('E2E Resistor 1k')
  await expect(page.getByTestId('results')).toContainText('E2E Resistor 22k')
  await expect(page.getByTestId('results')).not.toContainText('E2E Resistor bad')
})
