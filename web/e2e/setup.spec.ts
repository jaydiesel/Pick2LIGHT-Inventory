import { expect, test } from '@playwright/test'

import { PASSWORD } from './helpers'

test('first run wizard with password then login again', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/setup$/)
  await page.getByTestId('password').fill(PASSWORD)
  await page.getByTestId('confirm').fill(PASSWORD)
  await page.getByTestId('next').click()
  await expect(page.getByTestId('pack-batteries')).toBeChecked()
  await page.getByTestId('next').click()
  await page.getByTestId('finish').click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page).toHaveURL(/\/login/)
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
  await page.getByTestId('password').fill(PASSWORD)
  await page.getByTestId('login').click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  await page.context().storageState({ path: 'e2e/.auth/state.json' })
})
