/* global document */
// Screenshot tour for BEFORE/AFTER comparison. Fake model only; see aura_screens.py.
import { createRequire } from 'node:module'
import { mkdirSync } from 'node:fs'
const require = createRequire(new URL('../../apps/desktop/package.json', import.meta.url))
const { chromium, expect } = require('@playwright/test')

let input = ''
for await (const part of process.stdin) input += part
const { url, output } = JSON.parse(input)
mkdirSync(output, { recursive: true })
const origin = new URL(url).origin
const browser = await chromium.launch({
  executablePath: process.env.AURA_CHROMIUM || '/opt/pw-browsers/chromium',
  headless: true,
  args: ['--no-sandbox']
})
const sizes = { mobile: { width: 390, height: 844 }, desktop: { width: 1440, height: 900 } }
const shot = (page, name) => page.screenshot({ path: `${output}/${name}.png` })
const editor = page => page.locator('[contenteditable="true"]:visible').first()

async function send(page, text) {
  await editor(page).fill(text)
  const button = page.locator('form').getByRole('button', { name: 'Send', exact: true })
  await expect(button).toBeEnabled({ timeout: 60000 })
  await button.click()
}

async function settle(page) {
  await expect(page.locator('.aura-empty, [data-role]').first()).toBeVisible({ timeout: 60000 })
  await page.waitForFunction(() => !document.body.innerText.toLowerCase().includes('connecting'), null, { timeout: 60000 })
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(400)
}

async function openSettings(page) {
  const direct = page.getByRole('button', { name: 'Settings', exact: true }).filter({ visible: true })
  if (!(await direct.count())) await page.getByRole('button', { name: 'Open menu', exact: true }).click()
  await page.getByRole('button', { name: 'Settings', exact: true }).filter({ visible: true }).first().click()
  await settle(page)
}

async function closeOverlays(page) {
  await page.keyboard.press('Escape')
  await page.waitForTimeout(200)
}

try {
  for (const [label, viewport] of Object.entries(sizes)) {
    const anon = await browser.newPage({ viewport, colorScheme: 'light', reducedMotion: 'reduce' })
    await anon.goto(`${origin}/`)
    await anon.waitForTimeout(4000)
    await shot(anon, `signin-${label}`)
    await anon.close()
  }

  const page = await browser.newPage({ viewport: sizes.mobile, colorScheme: 'light', reducedMotion: 'reduce' })
  await page.goto(url)
  await expect(editor(page)).toBeVisible({ timeout: 60000 })
  await settle(page)
  await shot(page, 'home-mobile')

  await send(page, 'Synthetic: help me plan a small launch.')
  await expect(page.getByText('Ship to ten people', { exact: false }).first()).toBeVisible({ timeout: 60000 })
  await page.waitForTimeout(1500)
  await settle(page)
  await shot(page, 'thread-mobile')

  await send(page, 'Synthetic: run a harmless command, asking me first.')
  const approval = page.locator('[data-aura-card=approval]')
  await expect(approval).toBeVisible({ timeout: 60000 })
  await approval.scrollIntoViewIfNeeded()
  await settle(page)
  await shot(page, 'agent-mobile')
  await approval.getByRole('button', { name: /^(Change|Deny)/ }).first().click()
  await expect(page.getByText('Stub output: nothing was run.').first()).toBeVisible({ timeout: 60000 })

  await openSettings(page)
  await shot(page, 'settings-mobile')
  await closeOverlays(page)

  await page.setViewportSize(sizes.desktop)
  await page.reload()
  await expect(editor(page)).toBeVisible({ timeout: 60000 })
  await settle(page)
  await shot(page, 'thread-desktop')
  await approval.scrollIntoViewIfNeeded().catch(() => {})
  await shot(page, 'agent-desktop')
  await openSettings(page)
  await shot(page, 'settings-desktop')
  await closeOverlays(page)
  await page.getByRole('button', { name: /^New (conversation|chat)$/ }).filter({ visible: true }).first().click()
  await settle(page)
  await shot(page, 'home-desktop')
  if (await page.getByRole('button', { name: 'Add context', exact: true }).count()) {
    await page.getByRole('button', { name: 'Add context', exact: true }).click()
    await page.waitForTimeout(300)
    await shot(page, 'plus-menu-desktop')
    const tools = page.getByRole('menuitem', { name: /^Tools/ })
    if (await tools.count()) {
      await tools.click()
      await expect(page.getByRole('switch').first()).toBeVisible({ timeout: 30000 })
      await settle(page)
      await shot(page, 'tools-desktop')
    }
    await closeOverlays(page)
  }
  console.log(`Screens written to ${output}`)
} catch (error) {
  console.error(String(error))
  process.exitCode = 1
} finally {
  await browser.close()
}
