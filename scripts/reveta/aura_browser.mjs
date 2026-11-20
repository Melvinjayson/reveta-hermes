/* global document, getComputedStyle, innerWidth */
import { createRequire } from 'node:module'
import { mkdirSync, readFileSync } from 'node:fs'
import { productFlow } from './aura_product_browser.mjs'
import { voiceModeFlow } from './aura_pipecat_browser.mjs'
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

async function setTheme(page, mode) {
  const settings = page.getByRole('button', { name: 'Settings', exact: true }).filter({ visible: true })
  if (!(await settings.count())) await page.getByRole('button', { name: 'Open menu', exact: true }).click()
  await page.getByRole('button', { name: 'Settings', exact: true }).filter({ visible: true }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Settings' })
  await dialog.getByRole('combobox', { name: 'Theme' }).selectOption(mode)
  return dialog
}

async function closeSettings(page) {
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
}

async function openPanel(page, tab) {
  if (!(await page.locator('.aura-panel-tabs').isVisible().catch(() => false))) {
    await page.getByRole('button', { name: 'Open side panel', exact: true }).click()
  }
  await page.getByRole('tab', { name: tab, exact: true }).click()
}

async function closePanel(page) {
  await page.getByRole('button', { name: 'Close panel', exact: true }).click()
}

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
  } else if (launch.capabilities) {
    const editor = page.locator('[contenteditable="true"]:visible').first()
    const send = page.locator('form').getByRole('button', { name: 'Send', exact: true })
    const approval = page.locator('[data-aura-card=approval]')
    await editor.fill('Help me plan the launch.')
    await expect(send).toBeEnabled({ timeout: 60000 })
    await send.click()
    // Decision F: the question appears with no approval card in front of it.
    await expect(page.getByText('Founders').first()).toBeVisible({ timeout: 60000 })
    await expect(approval).toHaveCount(0)
    await page.getByText('Founders').first().click()
    await page.screenshot({ path: `${output}/clarify-mobile.png` })
    await page.getByRole('button', { name: /Confirm and continue/ }).click()
    await expect(page.getByText('Stub output: founders it is.')).toBeVisible({ timeout: 60000 })
    await editor.fill('Now search the site for pricing.')
    await expect(send).toBeEnabled({ timeout: 60000 })
    await send.click()
    await expect(approval).toContainText('browser_exec', { timeout: 60000 })
    await page.screenshot({ path: `${output}/browser-approval-mobile.png` })
    await approval.getByRole('button', { name: 'Change', exact: true }).click()
    await expect(page.getByText('Stub output: browser step declined.')).toBeVisible({ timeout: 60000 })
    console.log('PASS: unlocked clarify shows its choices with no approval tap; click-and-type browser waits for approval and Change runs nothing.')
  } else if (launch.voiceMode) {
    await voiceModeFlow(page, expect, output)
  } else if (launch.product) {
    await productFlow(page, expect, output)
  } else if (launch.costBlocked) {
    const blockedEditor = page.locator('[contenteditable="true"]:visible').first()
    await blockedEditor.fill('Synthetic blocked price check')
    await page.locator('form').getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.locator('[data-role=user]')).toContainText('Synthetic blocked price check', { timeout: 60000 })
    const refused = page.locator('[data-aura-step=Refused]')
    await expect(page.getByRole('button', { name: '1 step', exact: true })).toBeVisible({ timeout: 60000 })
    await openPanel(page, 'Work')
    await expect(refused).toHaveCount(1, { timeout: 60000 })
    await expect(refused.getByText("This would cost money, so I didn't run it.", { exact: true })).toBeVisible()
    console.log('PASS: non-allowlisted model refused as a step; no provider request.')
  } else if (launch.noModel) {
    await expect(page.locator('.aura-empty [role=status]')).toContainText(
      'Aura can’t reply yet. A model still needs to be connected.',
      { timeout: 60000 }
    )
    for (const mode of ['light', 'dark']) {
      await setTheme(page, mode)
      await closeSettings(page)
      await page.screenshot({ path: `${output}/no-model-${mode}.png` })
    }
    console.log('PASS: no-model notice in light and dark, without provider calls.')
  } else {
    await page.screenshot({ path: `${output}/empty-light.png` })
    const signin = await browser.newPage({ viewport: { width: 390, height: 844 } })
    await signin.goto(new URL(launch.url).origin + '/')
    await expect(signin.getByText('Sign in to Aura')).toBeVisible({ timeout: 60000 })
    await signin.close()
    const transition = await page
      .locator('.aura-header button')
      .first()
      .evaluate(e => getComputedStyle(e).transitionDuration)
    if (transition.split(',').some(value => parseFloat(value) !== 0))
      throw new Error('Reduced motion was not respected')
    for (const button of await page.locator('.aura-header button').filter({ visible: true }).all()) {
      const box = await button.boundingBox()
      if (!box || box.width < 44 || box.height < 44) throw new Error('Header touch target under 44px')
    }
    await expect(page.getByText('Simple mode', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Advanced mode', { exact: true })).toHaveCount(0)
    await expect(page.locator('.aura-suggestions button')).toHaveCount(4)
    await expect(page.getByRole('button', { name: 'Start voice chat', exact: true })).toBeVisible()
    for (const mode of ['light', 'dark']) {
      const settings = await setTheme(page, mode)
      for (const section of ['Appearance', 'Model', 'Memory', 'Skills', 'Scheduled jobs', 'Connectors', 'Voice', 'Account'])
        await expect(settings.getByRole('button', { name: section, exact: true })).toBeVisible()
      await page.screenshot({ path: `${output}/settings-${mode}.png` })
      await closeSettings(page)
      await page.getByRole('button', { name: 'Open menu', exact: true }).click()
      const drawer = page.getByRole('dialog', { name: 'Aura menu' })
      await expect(drawer).toBeVisible()
      for (const item of ['New chat', 'Search', 'Settings', 'New project'])
        await expect(drawer.getByRole('button', { name: item, exact: true })).toBeVisible()
      await page.screenshot({ path: `${output}/navigation-${mode}.png` })
      await page.keyboard.press('Escape')
      await expect(page.getByRole('button', { name: 'Open menu', exact: true })).toBeFocused()
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
    await expect(
      page.getByText('Stub output: A clear next step for your synthetic project.', { exact: false })
    ).toBeVisible({ timeout: 60000 })
    await expect(
      page
        .getByRole('navigation', { name: 'Sources for this reply' })
        .getByRole('link', { name: 'Source 1: Synthetic source', exact: true })
    ).toBeVisible()
    await expect(page.locator('[data-role=assistant]').last().getByRole('button', { name: /copy/i }).first()).toBeVisible()
    const text = await page.locator('body').innerText()
    if (/Hermes|Nous|NOUSRESEARCH/.test(text)) throw new Error('Upstream branding remains visible')
    for (const mode of ['dark', 'light']) {
      await setTheme(page, mode)
      await closeSettings(page)
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
    await page.setViewportSize({ width: 390, height: 844 })

    // Reopen and resume through the drawer (replaces the removed goal-card steps).
    await page.getByRole('button', { name: 'New chat', exact: true }).first().click()
    await expect(page.locator('.aura-empty')).toBeVisible()
    await page.getByRole('button', { name: 'Open menu', exact: true }).click()
    const history = page.getByRole('dialog', { name: 'Aura menu' }).locator('.aura-conversation-open').first()
    await expect(history).toBeVisible()
    await history.click()
    await page.locator('.aura-context-panel > summary').click({ timeout: 60000 })
    await expect(page.locator('[data-aura-card=resume]')).toBeVisible({ timeout: 60000 })
    await expect(page.locator('[data-role=assistant]')).toContainText('Stub output: A clear next step')
    for (const mode of ['light', 'dark']) {
      await setTheme(page, mode)
      await closeSettings(page)
      await page.locator('[data-aura-card=resume]').screenshot({ path: `${output}/resume-${mode}.png` })
      await openPanel(page, 'Sources')
      await page.locator('[data-aura-card=source]').first().screenshot({ path: `${output}/source-${mode}.png` })
      await closePanel(page)
    }
    await page.locator('.aura-context-panel > summary').click()

    // Search: titles and message text (server full-text search).
    await page.keyboard.press('Control+k')
    const search = page.getByRole('dialog', { name: 'Search conversations' })
    await expect(search).toBeVisible()
    await search.getByRole('combobox', { name: 'Search conversations' }).fill('clear next step')
    await expect(search.getByRole('group', { name: 'In messages' })).toBeVisible({ timeout: 30000 })
    await page.screenshot({ path: `${output}/search-light.png` })
    await page.keyboard.press('Escape')

    await setTheme(page, 'light')
    await closeSettings(page)
    const actionCount = () => JSON.parse(readFileSync(launch.target, 'utf8'))
    await editor.fill('Synthetic approval exercise: ask before the loopback mock action.')
    await editor.press('Enter')
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
      await setTheme(page, mode)
      await closeSettings(page)
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
    await openPanel(page, 'Work')
    const steps = page.locator('.aura-steps')
    await expect(steps.locator('[data-aura-step=Done]')).toHaveCount(1)
    await expect(steps.locator('[data-aura-step=Refused]')).toHaveCount(1)
    await expect(steps.getByText('Run a command in Aura’s workspace', { exact: true }).last()).toBeVisible()
    await steps.locator('[data-aura-step=Done]').getByText('Details', { exact: true }).click()
    await expect(steps.getByText('Exit code: 0', { exact: true })).toBeVisible()
    await expect(steps).not.toContainText(launch.target)
    for (const mode of ['light', 'dark']) {
      await page.screenshot({ path: `${output}/steps-${mode}.png` })
    }
    await closePanel(page)
    const context = await page.locator('.aura-context').boundingBox()
    const chat = await page.locator('[data-chat-surface]').boundingBox()
    expect(context.height).toBeLessThan(120)
    expect(chat.height).toBeGreaterThanOrEqual(844 * 0.6)
    console.log(`PASS: mobile strip ${context.height}px; chat ${chat.height}px at 390x844`)
    await page.screenshot({ path: `${output}/after-mobile.png` })
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.screenshot({ path: `${output}/after-desktop.png` })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.reload()
    await openPanel(page, 'Work')
    await expect(page.locator('.aura-steps [data-aura-step=Done]')).toHaveCount(1, { timeout: 60000 })
    if (actionCount() !== 1) throw new Error('Approved action executed more than once')
    await closePanel(page)
    await page.getByRole('button', { name: 'Add context', exact: true }).click()
    const imageBytes = await page.screenshot()
    const [chooser] = await Promise.all([
      page.waitForEvent('filechooser'),
      page.getByRole('menuitem', { name: /^Images/ }).click()
    ])
    await chooser.setFiles({ name: 'synthetic.png', mimeType: 'image/png', buffer: imageBytes })
    await expect(page.locator('[data-slot="composer-attachments"]')).toBeVisible()
    await page.getByRole('button', { name: 'Add context', exact: true }).click()
    await expect(page.getByRole('menuitemradio', { name: /^Focused/ })).toBeVisible()
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
    await page.getByRole('dialog', { name: 'Aura menu' }).getByRole('button', { name: 'Close menu', exact: true }).click()

    // Desktop: collapsible sidebar.
    await page.setViewportSize({ width: 1440, height: 900 })
    const rail = page.getByRole('complementary', { name: 'Conversation navigation' })
    await expect(rail).toBeVisible()
    await rail.getByRole('button', { name: 'Collapse sidebar', exact: true }).click()
    await expect(rail).toBeHidden()
    await page.getByRole('button', { name: 'Open menu', exact: true }).click()
    await expect(rail).toBeVisible()
    await page.screenshot({ path: `${output}/desktop-light.png` })

    // Delete a conversation: confirm first, then it leaves history.
    const rows = rail.locator('.aura-conversation-row')
    const before = await rows.count()
    await rows.first().getByRole('button', { name: /^Delete conversation:/ }).click()
    await rail.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(rows).toHaveCount(before)
    await rows.first().getByRole('button', { name: /^Delete conversation:/ }).click()
    await rail.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(rows).toHaveCount(before - 1, { timeout: 30000 })
    console.log(`PASS: delete asked first, then removed one of ${before} conversations`)
    await page.setViewportSize({ width: 390, height: 844 })

    const account = await setTheme(page, 'light')
    await account.getByRole('button', { name: 'Account', exact: true }).click()
    await account.getByRole('button', { name: 'Sign out', exact: true }).click()
    await expect(page.locator('[data-role="user"]')).toHaveCount(0)
    console.log(
      'PASS: sign-in gate, Simple-mode chat, fake streamed reply, numbered sources, drawer and sidebar navigation, message search, resume, approval once, steps panel, delete, themes, branding and viewport overflow checks.'
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
