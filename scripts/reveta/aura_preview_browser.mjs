/* Driver for aura_preview_browser.py: the release-preview flow behind the real sign-in gate. */
import { createRequire } from 'node:module'
import { readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
const require = createRequire(new URL('../../apps/desktop/package.json', import.meta.url))
const { chromium, expect } = require('@playwright/test')

let raw = ''
for await (const part of process.stdin) raw += part
const { url, user, password, home } = JSON.parse(raw)
const ok = name => console.log(`PASS ${name}`)
const evidenceDir = path.join(home, 'plugin-data', 'venus-evidence')
const records = () => {
  try {
    return readdirSync(evidenceDir)
      .filter(f => f.endsWith('.jsonl'))
      .flatMap(f => readFileSync(path.join(evidenceDir, f), 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse))
  } catch {
    return []
  }
}

const browser = await chromium.launch({ executablePath: process.env.AURA_CHROMIUM || '/usr/bin/chromium', headless: true,
  args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' })
try {
  // 1. Anonymous callers are refused; the owner signs in with the password form.
  const anon = await page.request.get(`${url}/api/aura/preview`, { maxRedirects: 0 })
  expect([401, 302, 303, 307]).toContain(anon.status())
  await page.goto(url)
  await page.locator('input[name=username]').fill(user)
  await page.locator('input[name=password]').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'What are you working on?' })).toBeVisible({ timeout: 60000 })
  ok('owner signs in behind the gate')

  // 2. Settings -> Preview: everything starts off; the owner switches all three on.
  const openSettings = async () => {
    await page.getByRole('button', { name: 'Settings', exact: true }).filter({ visible: true }).first().click()
    const dialog = page.getByRole('dialog', { name: 'Settings' })
    await dialog.getByRole('button', { name: 'Preview', exact: true }).click()
    return dialog
  }
  let dialog = await openSettings()
  const evidence = dialog.getByRole('switch', { name: 'Run evidence (Venus) enabled' })
  const companion = dialog.getByRole('switch', { name: 'Browser companion enabled' })
  const handoff = dialog.getByRole('switch', { name: 'Send tasks to your browser enabled' })
  await expect(evidence).not.toBeChecked()
  await expect(handoff).toBeDisabled()
  await evidence.click()
  await expect(evidence).toBeChecked()
  await companion.click()
  await expect(companion).toBeChecked()
  await expect(handoff).toBeEnabled()
  await handoff.click()
  await expect(handoff).toBeChecked()
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  ok('owner switches on run evidence, companion and handoff in Settings -> Preview')

  // 3. A chat turn writes one metadata-only evidence record.
  const editor = page.locator('[contenteditable="true"]:visible').first()
  await editor.fill('Help me plan the launch.')
  await page.locator('form').getByRole('button', { name: 'Send', exact: true }).click()
  await expect(page.getByText('Stub output: launch plan ready.').first()).toBeVisible({ timeout: 90000 })
  await expect.poll(() => records().filter(r => r.schema === 'venus.evidence.v1').length, { timeout: 30000 }).toBeGreaterThan(0)
  const run = records().find(r => r.schema === 'venus.evidence.v1')
  expect(run.provenance.source).toBe('measured_runtime')
  expect(run.outcome.status).toBe('completed')
  expect(run.api.succeeded).toBeGreaterThan(0)
  expect(JSON.stringify(run)).not.toContain('Help me plan the launch')
  expect(JSON.stringify(run)).not.toContain('launch plan ready')
  ok(`chat run wrote evidence record ${run.record_id} (no prompt or reply text in it)`)

  // 4. /venus-value: savings stay unknown until both minutes are in, then an amendment computes them.
  await editor.fill(`/venus-value ${run.record_id} baseline_minutes=60`)
  await page.locator('form').getByRole('button', { name: 'Send', exact: true }).click()
  await expect(page.getByText(/savings_minutes=unknown/).first()).toBeVisible({ timeout: 60000 })
  await editor.fill(`/venus-value ${run.record_id} human_review_minutes=15 comparison_method=manual`)
  await page.locator('form').getByRole('button', { name: 'Send', exact: true }).click()
  await expect(page.getByText(/savings_minutes=45\.0 \(computed\)/).first()).toBeVisible({ timeout: 60000 })
  const amendments = records().filter(r => r.schema === 'venus.evidence.amendment.v1' && r.amends_record_id === run.record_id)
  expect(amendments.map(a => a.value.savings_status)).toEqual(['unknown', 'computed'])
  ok('/venus-value appends amendments; savings unknown until both minutes, then 45.0')

  // 5. Browser handoff: the chat sends a task, the companion (its key, over HTTP) picks it up once and
  //    reports back; the result reaches the draft only on tap.
  await page.reload()
  const card = page.locator('[data-aura-card=browser-handoff]')
  await expect(card).toBeVisible({ timeout: 60000 })
  await card.locator('#aura-handoff-task').fill('Find the pricing page and note the Pro plan')
  await card.getByRole('button', { name: 'Send to browser' }).click()
  await expect(card.getByText('Open the Aura Companion side panel to start it.')).toBeVisible({ timeout: 30000 })
  const issued = await page.evaluate(async () => {
    const r = await fetch('/api/aura/companion/token', { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: '{}' })
    return { status: r.status, body: await r.json() }
  })
  expect(issued.status).toBe(200)
  const key = { Authorization: `Bearer ${issued.body.token}`, 'Content-Type': 'application/json' }
  const next = await fetch(`${url}/api/aura/companion/handoff/next`, { method: 'POST', headers: key, body: '{}' })
  expect(next.status).toBe(200)
  const task = await next.json()
  expect(JSON.stringify(task)).toContain('Find the pricing page')
  const handoffId = task.handoff?.id ?? task.id
  expect((await fetch(`${url}/api/aura/companion/handoff/next`, { method: 'POST', headers: key, body: '{}' })).status).toBe(204)
  const result = await fetch(`${url}/api/aura/companion/handoff/result`, { method: 'POST',
    headers: key,
    body: JSON.stringify({ id: handoffId, ok: true, summary: 'Pro plan is $20 a month.' }) })
  expect(result.status).toBe(200)
  await expect(card.getByText('From the web page, not checked by Aura:')).toBeVisible({ timeout: 30000 })
  await expect(card.getByText('Pro plan is $20 a month.')).toBeVisible()
  ok('handoff: chat -> companion key picks it up once -> result shown as unchecked page content')

  // 6. The companion's model call: this home keeps free_only on with an attested free fake model, so
  //    planning runs on the free route (the paid route is owner-and-cap gated; see the unit tests).
  const ask = await fetch(`${url}/api/aura/companion/ask`, { method: 'POST', headers: key,
    body: JSON.stringify({ messages: [{ role: 'user', content: 'Plan it' }],
      page: { intent: 'takeover', url: 'https://example.test/', title: 'T', excerpt: 'x' } }) })
  expect(ask.status).toBe(200)
  expect((await ask.json()).content.length).toBeGreaterThan(0)
  ok('companion planning answers on the free route with the owner key')
} catch (error) {
  console.log(`FAIL ${error.message.split('\n').slice(0, 6).join(' | ')}`)
  await page.screenshot({ path: path.join(home, '..', 'failure.png'), fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
