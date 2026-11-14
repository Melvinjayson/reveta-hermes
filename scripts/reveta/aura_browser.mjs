/* global document, getComputedStyle, innerWidth */
import { createRequire } from 'node:module'
import { mkdirSync, readFileSync } from 'node:fs'
import { productFlow } from './aura_product_browser.mjs'
const require = createRequire(new URL('../../apps/desktop/package.json', import.meta.url))
const { chromium, expect } = require('@playwright/test')
let url = ''
for await (const part of process.stdin) url += part
const launch = JSON.parse(url)
const output = process.env.AURA_SCREENSHOT_DIR || '.build/aura-screenshots'
mkdirSync(output, { recursive: true })
const browser = await chromium.launch({
  executablePath: process.env.AURA_CHROMIUM || '/usr/bin/chromium',
  headless: true,
  args: ['--no-sandbox', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']
})
const page = await browser.newPage({
  viewport: { width: 390, height: 844 },
  colorScheme: 'light',
  reducedMotion: 'reduce'
})
try {
  await page.goto(launch.url)
  await expect(page.locator('.aura-empty')).toBeVisible({ timeout: 60000 })
  await expect(page.getByRole('heading', { name: 'What are you working on?' })).toBeVisible()
  if (launch.retiredModel) {
    const editor = page.locator('[contenteditable="true"]:visible').first()
    await editor.fill('Synthetic retired-model check')
    await page.locator('form').getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.locator('.aui-error-card-title')).toContainText('Model unavailable', { timeout: 60000 })
    await expect(page.locator('.aui-error-card-body')).toContainText("doesn't offer")
    await page.screenshot({ path: `${output}/model-unavailable-mobile.png` })
    console.log('PASS: provider 404 shows Model unavailable; no retry or paid fallback.')
  } else if (launch.product) {
    await productFlow(page, expect, output)
  } else if (launch.costBlocked) {
    const blockedEditor = page.locator('[contenteditable="true"]:visible').first()
    await blockedEditor.fill('Synthetic blocked price check')
    await page.locator('form').getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.locator('[data-role=user]')).toContainText('Synthetic blocked price check', { timeout: 60000 })
    const refused = page.locator('[data-aura-step=Refused]')
    await expect(refused).toHaveCount(1, { timeout: 60000 })
    await page.locator('.aura-steps > summary').click()
    await expect(refused.getByText("This would cost money, so I didn't run it.", { exact: true })).toBeVisible()
    console.log('PASS: non-allowlisted model refused as a step; no provider request.')
  } else if (launch.noModel) {
    await expect(page.locator('.aura-empty [role=status]')).toContainText(
      'Aura can’t reply yet. A model still needs to be connected.',
      { timeout: 60000 }
    )
    for (const mode of ['light', 'dark']) {
      await page.getByRole('button', { name: 'Open menu', exact: true }).click()
      await page.getByRole('dialog').getByRole('button', { name: 'Settings', exact: true }).click()
      await page.getByRole('dialog').getByRole('combobox').selectOption(mode)
      await page.getByRole('dialog').getByRole('button', { name: 'Close menu', exact: true }).click()
      await page.screenshot({ path: `${output}/no-model-${mode}.png` })
    }
    console.log('PASS: no-model notice in light and dark, without provider calls.')
  } else {
    await page.screenshot({ path: `${output}/empty-light.png` })
    const transition = await page
      .locator('.aura-header button')
      .first()
      .evaluate(e => getComputedStyle(e).transitionDuration)
    if (transition.split(',').some(value => parseFloat(value) !== 0))
      throw new Error('Reduced motion was not respected')
    for (const button of await page.locator('.aura-header button').all()) {
      const box = await button.boundingBox()
      if (!box || box.width < 44 || box.height < 44) throw new Error('Header touch target under 44px')
    }
    await expect(page.getByText('Simple mode', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Advanced mode', { exact: true })).toHaveCount(0)
    for (const mode of ['light', 'dark']) {
      await page.getByRole('button', { name: 'Open menu', exact: true }).click()
      await expect(page.getByRole('dialog', { name: 'Aura menu' })).toBeVisible()

      await page.getByRole('dialog').getByRole('button', { name: 'Settings', exact: true }).click()
      await page.getByRole('dialog').getByRole('combobox').selectOption(mode)
      await page.screenshot({ path: `${output}/settings-${mode}.png` })
      await page.getByRole('dialog').getByRole('button', { name: 'Conversations', exact: true }).click()
      await page.screenshot({ path: `${output}/navigation-${mode}.png` })
      if (mode === 'light') {
        await page.keyboard.press('Escape')
        await expect(page.getByRole('button', { name: 'Open menu', exact: true })).toBeFocused()
      } else await page.getByRole('dialog').getByRole('button', { name: 'Close menu' }).click()
      await page.screenshot({ path: `${output}/empty-${mode}.png` })
    }
    const editor = page.locator('[contenteditable="true"]:visible').first()
    await page.evaluate(() => document.fonts.ready)
    await editor.fill('Synthetic project: help me choose one next step.')
    await editor.press('Enter')
    await expect(page.locator('form').getByRole('button', { name: 'Stop', exact: true })).toBeVisible({
      timeout: 60000
    })
    await page.screenshot({ path: `${output}/streaming-dark.png` })
    await expect(page.locator('[data-role=assistant]')).toContainText('Stub output:', { timeout: 60000 })
    await expect(page.locator('[data-aura-card=progress]')).toHaveCount(0)
    await page.locator('.aura-context').evaluate(node => (node.scrollTop = node.scrollHeight))
    await page.screenshot({ path: `${output}/progress-dark.png` })
    await expect(
      page.getByText('Stub output: A clear next step for your synthetic project.', { exact: false })
    ).toBeVisible({ timeout: 60000 })

    await expect(
      page
        .getByRole('navigation', { name: 'Sources for this reply' })
        .getByRole('link', { name: 'Synthetic source', exact: false })
    ).toBeVisible()
    const text = await page.locator('body').innerText()
    if (/Hermes|Nous|NOUSRESEARCH/.test(text)) throw new Error('Upstream branding remains visible')
    for (const mode of ['dark', 'light']) {
      await page.getByRole('button', { name: 'Open menu', exact: true }).click()
      await page.getByRole('dialog').getByRole('button', { name: 'Settings', exact: true }).click()
      await page.getByRole('dialog').getByRole('combobox').selectOption(mode)
      await page.getByRole('dialog').getByRole('button', { name: 'Close menu' }).click()
      await page.screenshot({ path: `${output}/conversation-${mode}.png` })
      await page.setViewportSize({ width: 390, height: 500 })
      await editor.focus()
      await editor.fill('A synthetic draft above the emulated keyboard.')
      await expect(page.locator('[data-slot="composer-surface"]')).toBeInViewport()
      await page.screenshot({ path: `${output}/keyboard-${mode}.png` })
      await editor.fill('')
      await page.setViewportSize({ width: 390, height: 844 })
    }
    for (const [width, height] of [
      [320, 640],
      [375, 812],
      [390, 844]
    ]) {
      await page.setViewportSize({ width, height })
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
      if (overflow) throw new Error(`Horizontal overflow at ${width}`)
    }
    await page.setViewportSize({ width: 390, height: 500 })
    await expect(page.locator('[data-slot="composer-surface"]')).toBeInViewport()
    await editor.fill('A synthetic draft\nwith several lines\nthat stays above the keyboard.')
    await page.screenshot({ path: `${output}/keyboard-light.png` })
    await editor.fill('')
    await page.setViewportSize({ width: 390, height: 844 })
    await page.locator('[data-aura-card=goal]').screenshot({ path: `${output}/goal-light.png` })
    await page.getByRole('button', { name: 'Edit goal', exact: true }).click()
    await page.getByLabel('Your goal').fill('A clearer synthetic project goal')
    await page.getByRole('button', { name: 'Save goal', exact: true }).click()
    await expect(page.locator('[data-aura-card=goal]')).toContainText('A clearer synthetic project goal')
    await page.getByRole('button', { name: 'New conversation', exact: true }).first().click()
    await expect(page.locator('.aura-empty')).toBeVisible()
    await page.getByRole('button', { name: 'Open menu', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Conversations', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Search', exact: true }).click()
    await page.getByRole('textbox', { name: 'Search conversations', exact: true }).fill('')
    const history = page.getByRole('dialog').locator('.aura-conversations section button').first()
    await expect(history).toBeVisible()
    await history.click()
    await expect(page.locator('[data-aura-card=resume]')).toBeVisible()
    await expect(page.locator('[data-aura-card=resume]')).toContainText('A clearer synthetic project goal')
    for (const mode of ['light', 'dark']) {
      await page.getByRole('button', { name: 'Open menu', exact: true }).click()
      await page.getByRole('dialog').getByRole('button', { name: 'Settings', exact: true }).click()
      await page.getByRole('dialog').getByRole('combobox').selectOption(mode)
      await page.getByRole('dialog').getByRole('button', { name: 'Close menu', exact: true }).click()
      await page.locator('[data-aura-card=goal]').screenshot({ path: `${output}/goal-${mode}.png` })
      await page.locator('[data-aura-card=resume]').screenshot({ path: `${output}/resume-${mode}.png` })
      await page.locator('.aura-context summary').click()
      await page
        .locator('[data-aura-card=source]')
        .first()
        .screenshot({ path: `${output}/source-${mode}.png` })
      await page.locator('.aura-context summary').click()
    }
    await page.getByRole('button', { name: 'Open menu', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Settings', exact: true }).click()
    await page.getByRole('dialog').getByRole('combobox').selectOption('light')
    await page.getByRole('dialog').getByRole('button', { name: 'Close menu', exact: true }).click()
    const actionCount = () => JSON.parse(readFileSync(launch.target, 'utf8'))
    await editor.fill('Synthetic approval exercise: ask before the loopback mock action.')
    await editor.press('Enter')
    await page.locator('.aura-context').evaluate(node => (node.scrollTop = node.scrollHeight))
    await page.screenshot({ path: `${output}/progress-light.png` })
    const approval = page.locator('[data-aura-card=approval]')
    await expect(approval).toBeVisible({ timeout: 60000 })
    if (actionCount() !== 0) throw new Error('Mock action ran before approval')
    await expect(approval.getByRole('button')).toHaveCount(2)
    await approval.getByRole('button', { name: 'Change', exact: true }).click()
    await expect(page.locator('[data-role=assistant]').getByText('Stub output: Synthetic action was not run.', { exact: true }))
      .toBeVisible({ timeout: 60000 })
    if (actionCount() !== 0) throw new Error('Change executed the mock action')
    await editor.fill('Retry the synthetic mock action, asking for approval again.')
    await editor.press('Enter')
    await expect(approval).toBeVisible({ timeout: 60000 })
    for (const mode of ['dark', 'light']) {
      await page.getByRole('button', { name: 'Open menu', exact: true }).click()
      await page.getByRole('dialog').getByRole('button', { name: 'Settings', exact: true }).click()
      await page.getByRole('dialog').getByRole('combobox').selectOption(mode)
      await page.getByRole('dialog').getByRole('button', { name: 'Close menu', exact: true }).click()
      await approval.screenshot({ path: `${output}/approval-${mode}.png` })
    }
    if (actionCount() !== 0) throw new Error('Mock action ran while reviewing')
    await approval.getByRole('button', { name: /^Approve/ }).click()
    await expect.poll(actionCount, { timeout: 60000 }).toBe(1)
    await expect(
      page
        .locator('[data-role=assistant]')
        .getByText('Stub output: Approved synthetic action complete.', { exact: true })
    ).toBeVisible({
      timeout: 60000
    })
    const steps = page.locator('.aura-steps')
    await steps.locator(':scope > summary').click()
    await expect(steps.locator('[data-aura-step=Done]')).toHaveCount(1)
    await expect(steps.locator('[data-aura-step=Refused]')).toHaveCount(1)
    await expect(steps.getByText('Run a command in Aura’s workspace', { exact: true }).last()).toBeVisible()
    await steps.locator('[data-aura-step=Done]').getByText('Details', { exact: true }).click()
    await expect(steps.getByText('Exit code: 0', { exact: true })).toBeVisible()
    await expect(steps).not.toContainText(launch.target)
    await steps.locator('[data-aura-step=Done]').getByText('Details', { exact: true }).click()
    for (const mode of ['light', 'dark']) {
      await page.getByRole('button', { name: 'Open menu', exact: true }).click()
      await page.getByRole('dialog').getByRole('button', { name: 'Settings', exact: true }).click()
      await page.getByRole('dialog').getByRole('combobox').selectOption(mode)
      await page.getByRole('dialog').getByRole('button', { name: 'Close menu', exact: true }).click()
      await page.locator('.aura-context').evaluate(node => (node.scrollTop = node.scrollHeight))
      await page.screenshot({ path: `${output}/steps-${mode}.png` })
    }
    await page.reload()
    await expect(steps.locator('[data-aura-step=Done]')).toHaveCount(1)
    await steps.locator(':scope > summary').click()
    await expect(steps.getByText('Run a command in Aura’s workspace', { exact: true }).last()).toBeVisible()
    if (actionCount() !== 1) throw new Error('Approved action executed more than once')
    await page.getByRole('button', { name: 'Open menu', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Close menu', exact: true }).click()
    await page.getByRole('button', { name: 'Add context', exact: true }).click()
    const imageBytes = await page.screenshot()
    const [chooser] = await Promise.all([
      page.waitForEvent('filechooser'),
      page.getByRole('menuitem', { name: /^Images/ }).click()
    ])
    await chooser.setFiles({ name: 'synthetic.png', mimeType: 'image/png', buffer: imageBytes })
    await expect(page.locator('[data-slot="composer-attachments"]')).toBeVisible()
    await page.getByRole('button', { name: 'Add context', exact: true }).click()
    await page.getByRole('menuitem', { name: /^URL/ }).click()
    await page
      .getByRole('textbox', { name: 'Attach a URL', exact: true })
      .fill('https://example.test/synthetic-context')
    await page.getByRole('dialog').getByRole('button', { name: 'Attach', exact: true }).click()
    await expect(page.locator('[data-slot="composer-attachments"]')).toContainText('example.test')
    await page.screenshot({ path: `${output}/attachments-light.png` })
    await page.locator('[data-role=assistant]').first().dispatchEvent('contextmenu')
    await page.getByRole('button', { name: 'Continue later', exact: true }).first().click()
    await expect(page.getByRole('dialog', { name: 'Aura menu' })).toBeVisible()
    await page.getByRole('dialog').getByRole('button', { name: 'Close menu', exact: true }).click()
    await page.setViewportSize({ width: 1280, height: 900 })
    await expect(page.getByRole('complementary', { name: 'Conversation navigation' })).toBeVisible()
    await page.getByRole('button', { name: 'Open menu', exact: true }).click()
    await expect(page.getByRole('complementary', { name: 'Conversation navigation' })).toBeHidden()
    await page.getByRole('button', { name: 'Open menu', exact: true }).click()
    await expect(page.getByRole('complementary', { name: 'Conversation navigation' })).toBeVisible()
    await page.screenshot({ path: `${output}/desktop-light.png` })
    await page.setViewportSize({ width: 390, height: 844 })

    await page.getByRole('button', { name: 'Open menu', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Sign out', exact: true }).click()
    await expect(page.locator('[data-role="user"]')).toHaveCount(0)
    console.log(
      'PASS: private sign-in, Simple-mode chat, fake streamed reply, navigation, themes, branding and viewport overflow checks.'
    )
  }
} catch (error) {
  await page.screenshot({ path: `${output}/failure.png` })
  console.error(String(error))
  // Do not dump page text: a failed auth page may contain a private link.
  process.exitCode = 1
} finally {
  await browser.close()
}
