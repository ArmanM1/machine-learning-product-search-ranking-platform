import { expect, test } from '@playwright/test'

test('reviewer can move from overview to comparison and evidence', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /machine learning product search ranking platform/i })).toBeVisible()
  await expect(page.getByText(/illustrative fixture/i).first()).toBeVisible()

  await page.getByRole('link', { name: /compare a query/i }).click()
  await expect(page.getByRole('heading', { name: /quiet keyboard for office/i })).toBeVisible()
  await expect(page.getByLabel(/moved .* up from rank/i).first()).toBeVisible()

  await page.getByRole('checkbox', { name: /show benchmark labels/i }).uncheck()
  await page.getByRole('link', { name: /view aggregate evidence/i }).click()
  await expect(page.getByRole('heading', { name: /aggregate evidence/i })).toBeVisible()
})

test('failure filters and experiment provenance work on a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 })
  await page.goto('/failures')
  await page.getByRole('button', { name: 'Losses' }).click()
  await expect(page.getByRole('heading', { name: /apple watch band leather/i })).toBeVisible()

  await page.goto('/experiments/run-demo-fixture')
  await expect(page.getByRole('heading', { name: /immutable chain of evidence/i })).toBeVisible()
  await expect(page.getByText(/no cloud run has been recorded/i)).toBeVisible()
})

test('keyboard-only navigation exposes focus and reaches comparison', async ({ page }) => {
  await page.goto('/')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: /skip to content/i })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main-content')).toBeFocused()
})
