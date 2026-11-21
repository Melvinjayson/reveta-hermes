import { createRequire } from 'node:module'
const require = createRequire('/home/user/reveta-hermes/apps/desktop/package.json')
const { chromium, expect } = require('@playwright/test')
let input = ''
for await (const part of process.stdin) input += part
const { url } = JSON.parse(input) // run via: AURA_SCREENS_SCRIPT=scripts/reveta/aura_latency.mjs python scripts/reveta/aura_screens.py OUT (plain-text fake replies only)
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
const ed = () => page.locator('[contenteditable="true"]:visible').first()
const rows = []
try {
  await page.goto(url)
  await expect(ed()).toBeVisible({ timeout: 60000 })
  for (let i = 0; i < 10; i++) {
    const before = await page.locator('[data-role=assistant]').count()
    await ed().fill(`Synthetic latency probe ${i}`)
    const send = page.locator('form').getByRole('button', { name: 'Send', exact: true })
    await expect(send).toBeEnabled({ timeout: 60000 })
    const t0 = Date.now()
    await send.click()
    await page.locator('[data-role=user]').nth(i).waitFor({ timeout: 60000 })
    const tUser = Date.now()
    await expect(page.locator('[data-role=assistant]')).toHaveCount(before + 1, { timeout: 120000 })
    await page.locator('[data-role=assistant]').last().getByText(/\S/).first().waitFor({ timeout: 120000 })
    const tFirst = Date.now()
    await expect(page.locator('form').getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0, { timeout: 120000 })
    const tDone = Date.now()
    rows.push({ i, userEcho: tUser - t0, firstText: tFirst - t0, done: tDone - t0 })
  }
  const q = (k, p) => { const v = rows.map(r => r[k]).sort((a, b) => a - b); return v[Math.min(v.length - 1, Math.floor(p * v.length))] }
  console.log(JSON.stringify({ n: rows.length, rows, p50: { userEcho: q('userEcho', .5), firstText: q('firstText', .5), done: q('done', .5) }, p95: { userEcho: q('userEcho', .95), firstText: q('firstText', .95), done: q('done', .95) } }))
} catch (e) { console.error('FAILED AT', rows.length, JSON.stringify(rows)); console.error(String(e).slice(0, 300)); await page.screenshot({ path: (process.env.AURA_SCREENSHOT_DIR || '.build') + '/latency-fail.png' }); console.error('MAIN', (await page.locator('main').innerText()).slice(-900)); process.exitCode = 1 } finally { await browser.close() }
