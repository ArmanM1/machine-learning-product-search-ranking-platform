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

test('evaluation keeps wide evidence inside bounded scrollers on a 360px viewport', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 })
  await page.goto('/evaluation')
  await expect(page.getByRole('heading', { name: /aggregate evidence/i })).toBeVisible()

  const layout = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth
    const scrollRegions = Array.from(document.querySelectorAll<HTMLElement>('.table-scroll')).map((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      left: element.getBoundingClientRect().left,
      right: element.getBoundingClientRect().right,
    }))
    const experiment = document.querySelector<HTMLElement>('.primary-nav a:last-child')
    const experimentRect = experiment?.getBoundingClientRect()
    return {
      viewportWidth,
      documentWidth: document.documentElement.scrollWidth,
      scrollRegions,
      experiment: experimentRect ? { left: experimentRect.left, right: experimentRect.right } : null,
    }
  })

  expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth)
  expect(layout.scrollRegions.length).toBeGreaterThan(0)
  expect(layout.scrollRegions.some((region) => region.scrollWidth > region.clientWidth)).toBe(true)
  expect(layout.scrollRegions.every((region) => region.left >= 0 && region.right <= layout.viewportWidth)).toBe(true)
  expect(layout.experiment).not.toBeNull()
  expect(layout.experiment!.left).toBeGreaterThanOrEqual(0)
  expect(layout.experiment!.right).toBeLessThanOrEqual(layout.viewportWidth)
  await expect(page.getByRole('link', { name: 'Experiment' })).toBeVisible()
})

test('normal-text utility colors meet WCAG AA contrast', async ({ page }) => {
  await page.goto('/failures')
  const tieBadge = page.locator('.outcome-label.tie')
  await expect(tieBadge).toBeVisible()

  const ratios = await tieBadge.evaluate((badge) => {
    const channels = (value: string) => {
      const color = value.trim()
      if (color.startsWith('#')) {
        const hex = color.slice(1)
        return [0, 2, 4].map((index) => Number.parseInt(hex.slice(index, index + 2), 16))
      }
      return (color.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number)
    }
    const luminance = (value: string) => {
      const [red, green, blue] = channels(value).map((channel) => {
        const normalized = channel / 255
        return normalized <= 0.04045
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * red + 0.7152 * green + 0.0722 * blue
    }
    const contrast = (foreground: string, background: string) => {
      const values = [luminance(foreground), luminance(background)].sort((left, right) => right - left)
      return (values[0] + 0.05) / (values[1] + 0.05)
    }
    const tokens = getComputedStyle(document.documentElement)
    const badgeStyle = getComputedStyle(badge)
    return {
      quietOnCanvas: contrast(tokens.getPropertyValue('--quiet'), tokens.getPropertyValue('--canvas')),
      quietOnPaper: contrast(tokens.getPropertyValue('--quiet'), tokens.getPropertyValue('--paper')),
      tieBadge: contrast(badgeStyle.color, badgeStyle.backgroundColor),
    }
  })

  for (const ratio of Object.values(ratios)) expect(ratio).toBeGreaterThanOrEqual(4.5)
})

test('keyboard-only navigation updates the route title, announcement, and heading focus', async ({ page }) => {
  await page.goto('/')
  const skipLink = page.getByRole('link', { name: /skip to content/i })
  await expect(skipLink).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(skipLink).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main-content')).toBeFocused()

  await page.goto('/')
  const compareLink = page.getByRole('link', { name: 'Compare', exact: true })
  for (let step = 0; step < 8 && !(await compareLink.evaluate((link) => link === document.activeElement)); step += 1) {
    await page.keyboard.press('Tab')
  }
  await expect(compareLink).toBeFocused()
  await page.keyboard.press('Enter')

  await expect(page).toHaveTitle('Query comparison | Rank / evidence')
  await expect(page.getByRole('status')).toHaveText(/query comparison page loaded/i)
  await expect(page.getByRole('heading', { level: 1, name: /see what moved/i })).toBeFocused()
})
