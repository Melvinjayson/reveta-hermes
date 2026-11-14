/* global window */
import { readFileSync } from 'node:fs'
import { installVoiceFixture, continuousVoiceFlow } from './aura_pipecat_browser.mjs'

async function openPanel(page, tab) {
  if (!(await page.locator('.aura-panel-tabs').isVisible().catch(() => false))) {
    await page.getByRole('button', { name: 'Open side panel', exact: true }).click()
  }
  await page.getByRole('tab', { name: tab, exact: true }).click()
}

async function closePanel(page) {
  await page.getByRole('button', { name: 'Close panel', exact: true }).click()
}

/** Run against the real Webapp/gateway; only speech hardware and the model are fakes. */
export async function productFlow(page, expect, output) {
  await page.addInitScript(() => {
    const state = { mic: null, utterance: null, cancels: 0 }
    class Recognition {
      start() { state.mic = this }
      abort() { this.onend?.() }
    }
    window.SpeechRecognition = Recognition
    window.SpeechSynthesisUtterance = class { constructor(text) { this.text = text } }
    Object.defineProperty(window, 'speechSynthesis', { value: {
      speak(utterance) { state.utterance = utterance },
      cancel() { state.cancels++ }
    } })
    window.auraVoiceFixture = {
      interim(text) { state.mic.onresult({ resultIndex: 0, results: [{ isFinal: false, 0: { transcript: text } }] }) },
      final(text) { state.mic.onresult({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: text } }] }) },
      error() { state.mic.onerror({ error: 'not-allowed' }) },
      state
    }
  })
  const fixture = await installVoiceFixture(page)
  await page.reload()
  const editor = page.locator('[contenteditable="true"]:visible').first()
  await editor.fill('Research HTTP client requests and give me a one-page brief')
  const send = page.locator('form').getByRole('button', { name: 'Send', exact: true })
  await expect(send).toBeEnabled({ timeout: 60000 })
  await send.click()
  await expect(page.locator('[data-role=assistant]').filter({ hasText: 'I will read three sources' }).first()).toBeVisible({ timeout: 60000 })
  const approval = page.locator('[data-aura-card=approval]')
  await expect(approval).toContainText('pwd', { timeout: 180000 })
  await approval.getByRole('button', { name: /^Approve/ }).click()
  await expect(page.getByRole('group', { name: 'This chat' }).getByRole('button', { name: '1 file', exact: true })).toBeVisible({ timeout: 180000 })
  await expect(page.locator('[data-role=assistant]').last()).toContainText('Brief ready', { timeout: 180000 })
  await openPanel(page, 'Work')
  const steps = page.locator('.aura-steps')
  await expect(steps.locator('[data-aura-step=Done]')).toHaveCount(5)
  await expect(steps).toContainText('Run a command in Aura’s workspace')
  const terminal = steps.locator('[data-aura-step=Done]').filter({ hasText: 'Run a command in Aura’s workspace' })
  await terminal.getByText('Details', { exact: true }).click()
  await expect(terminal).toContainText('pwd')
  await expect(terminal).toContainText('Exit code: 0')
  await expect(steps).toContainText('python/cpython')
  await expect(steps).toContainText('nodejs/node')
  await expect(steps).toContainText('curl/curl')
  await steps.screenshot({ path: `${output}/product-steps-mobile.png` })
  await closePanel(page)
  await expect(page.locator('[data-role=assistant]').last()).toContainText('Brief ready')
  await openPanel(page, 'Files')
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download brief.md', exact: true }).click()
  ])
  if (await download.failure()) { throw new Error('Brief download failed') }
  const bytes = readFileSync(await download.path(), 'utf8')
  for (const text of ['# HTTP client requests', 'https://raw.githubusercontent.com/python/cpython', 'https://raw.githubusercontent.com/nodejs/node', 'https://raw.githubusercontent.com/curl/curl']) {
    if (!bytes.includes(text)) { throw new Error(`Brief lacks expected citation/content: ${text}`) }
  }
  await page.getByRole('button', { name: /brief\.md/ }).first().click()
  await expect(page.locator('.aura-file-preview')).toContainText('HTTP client requests', { timeout: 30000 })
  await page.screenshot({ path: `${output}/product-file-preview-mobile.png` })
  await closePanel(page)
  await page.screenshot({ path: `${output}/product-research-mobile.png` })
  await page.reload()
  await openPanel(page, 'Files')
  await expect(page.getByRole('button', { name: 'Download brief.md', exact: true })).toBeVisible({ timeout: 60000 })
  await page.getByRole('tab', { name: 'Work' }).click()
  await expect(page.locator('[data-aura-step=Done]')).toHaveCount(5)
  await closePanel(page)
  await page.getByRole('button', { name: 'New chat', exact: true }).first().click()
  await page.getByRole('button', { name: 'Open menu', exact: true }).click()
  await page.getByRole('dialog', { name: 'Aura menu' }).locator('.aura-conversation-open').first().click()
  await openPanel(page, 'Files')
  await expect(page.getByRole('button', { name: 'Download brief.md', exact: true })).toBeVisible()
  await closePanel(page)

  const voice = page.getByRole('group', { name: 'Voice chat' })
  // Chromium's synthetic microphone exercises device access only. Recognition
  // and speech playback below remain explicit fakes, not a live STT/TTS claim.
  const audioTracks = await page.evaluate(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    try { return stream.getAudioTracks().length } finally { stream.getTracks().forEach(track => track.stop()) }
  })
  expect(audioTracks).toBe(1)
  await voice.getByRole('button', { name: 'Start voice chat', exact: true }).click()
  await expect(voice, 'voice listens immediately after enabling').toHaveAttribute('data-aura-voice', 'Listening')
  await page.evaluate(() => window.auraVoiceFixture.interim('What should I remember'))
  await expect(voice.getByLabel('Live transcript')).toContainText('What should I remember')
  await page.evaluate(() => window.auraVoiceFixture.final('What should I remember from the brief?'))
  await expect(page.locator('[data-role=user]').last()).toContainText('What should I remember from the brief?')
  await expect(voice).toHaveAttribute('data-aura-voice', 'Thinking')
  await expect(voice).toHaveAttribute('data-aura-voice', 'Speaking', { timeout: 60000 })
  await page.evaluate(() => window.auraVoiceFixture.final('What should I remember from the brief?'))
  await expect(page.locator('[data-role=user]').filter({ hasText: 'What should I remember from the brief?' })).toHaveCount(1)
  await voice.getByRole('button', { name: 'Interrupt and listen', exact: true }).click()
  await expect(voice, 'interrupt returns fallback to listening').toHaveAttribute('data-aura-voice', 'Listening')
  const cancels = await page.evaluate(() => window.auraVoiceFixture.state.cancels)
  if (!cancels) { throw new Error('Barge-in did not cancel speech') }
  await page.screenshot({ path: `${output}/product-voice-mobile.png` })
  await page.evaluate(() => window.auraVoiceFixture.error())
  await expect(voice.getByRole('alert')).toContainText('not-allowed')
  await expect(voice).toHaveAttribute('data-aura-voice', 'off')
  await page.reload()
  await expect(page.locator('[data-role=user]').last()).toContainText('What should I remember from the brief?')
  await openPanel(page, 'Files')
  await expect(page.getByRole('button', { name: 'Download brief.md', exact: true })).toBeVisible()
  await closePanel(page)
  console.log('PASS: mobile research plan → three real sources → Hermes file adapter → cited download → reload/reopen; fake speech UI listening/transcript/thinking/speaking/barge-in/denial, same chat context.')
}
