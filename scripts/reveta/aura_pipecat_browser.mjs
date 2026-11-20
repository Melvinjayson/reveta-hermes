/** Phone acceptance: real app + Hermes gateway, explicit fake STT/TTS and synthetic microphone. */
export async function installVoiceFixture(page) {
  let socket, seq = 0, acked = false, changedPlayed = false, microphoneFrames = 0, reply = '', firstSent = false
  const turn = 'a'.repeat(32), changed = 'b'.repeat(32)
  const pcm = duration => Buffer.alloc(16000 * 2 * duration).toString('base64')
  const emit = event => socket.send(JSON.stringify({ ...event, epoch: 'phone-fixture', seq: ++seq }))
  await page.routeWebSocket('**/api/audio/pipecat?**', ws => {
    socket = ws
    ws.onMessage(raw => {
      const event = JSON.parse(String(raw))
      if (event.type === 'hello') { emit({ type: 'ready' }) }
      if (event.type === 'audio') { microphoneFrames++ }
      if (event.type === 'ack' && event.packet_id === 'first') {
        acked = true
        emit({ type: 'played', turn_id: turn, message_index: 0, text: 'Remember the HTTP methods.', interrupted: false })
      }
      if (event.type === 'ack' && event.packet_id === 'changed') {
        changedPlayed = true
        emit({ type: 'played', turn_id: changed, message_index: 0, text: 'Status codes describe the HTTP response.', interrupted: false })
      }
      if (event.type === 'reply' && event.turn_id === changed && event.done) {
        emit({ type: 'audio', turn_id: changed, packet_id: 'changed', message_index: 0,
          text: 'Status codes describe the HTTP response.', sample_rate: 16000, pcm: pcm(0.1) })
      }
      if (event.type === 'reply' && event.turn_id === turn) {
        reply += event.text
        if (!firstSent && reply.includes('Remember the HTTP methods.')) {
          firstSent = true
          emit({ type: 'audio', turn_id: turn, packet_id: 'first', message_index: 0,
            text: 'Remember the HTTP methods.', sample_rate: 16000, pcm: pcm(0.1) })
          emit({ type: 'audio', turn_id: turn, packet_id: 'unplayed', message_index: 0,
            text: 'This remainder must be flushed.', sample_rate: 16000, pcm: pcm(8) })
        }
      }
    })
  })
  return { emit, turn, changed, get connected() { return Boolean(socket) }, get acked() { return acked }, get changedPlayed() { return changedPlayed }, get microphoneFrames() { return microphoneFrames } }
}

export async function continuousVoiceFlow(page, expect, output, fixture) {
  const voice = page.getByLabel('Continuous voice')
  await voice.getByRole('button', { name: 'Voice', exact: true }).click()
  await expect(voice).toContainText('Listening')
  await expect.poll(() => fixture.connected).toBe(true)
  fixture.emit({ type: 'partial', turn_id: fixture.turn, text: 'What should I remember' })
  await expect(voice).toContainText('What should I remember')
  await expect.poll(() => fixture.microphoneFrames).toBeGreaterThan(0)
  await expect(page.locator('[data-role=user]').filter({ hasText: 'What should I remember' })).toHaveCount(0)
  fixture.emit({ type: 'speech_end', turn_id: fixture.turn })
  for (let i = 0; i < 2; i++) { fixture.emit({ type: 'final', turn_id: fixture.turn, text: 'What should I remember from the brief?' }) }
  await expect(page.locator('[data-role=user]').filter({ hasText: 'What should I remember from the brief?' })).toHaveCount(1)
  await expect.poll(() => fixture.acked).toBe(true)
  await expect(voice).toContainText('Speaking')
  fixture.emit({ type: 'speech_start', turn_id: fixture.changed, interrupt_turn_id: fixture.turn })
  fixture.emit({ type: 'played', turn_id: fixture.turn, message_index: 0, text: 'Remember the HTTP methods.', interrupted: true })
  await expect(voice).toContainText('Interrupted')
  fixture.emit({ type: 'final', turn_id: fixture.changed, text: 'Change that to a short answer about status codes.' })
  await expect(page.locator('[data-role=user]').filter({ hasText: 'Change that to a short answer about status codes.' })).toHaveCount(1, { timeout: 60000 })
  await expect(page.locator('[data-role=assistant]').last()).toContainText('Status codes describe the HTTP response.', { timeout: 60000 })
  await expect.poll(() => fixture.changedPlayed).toBe(true)
  await expect(voice).toContainText('Listening')
  await expect(page.locator('[data-role=assistant]').filter({ hasText: 'Remember the HTTP methods.' })).toHaveCount(1)
  await page.screenshot({ path: `${output}/pipecat-voice-mobile.png` })
  await voice.getByRole('button', { name: 'Mic on', exact: true }).click()
  await page.reload()
  await expect(page.locator('[data-role=assistant]').filter({ hasText: 'Remember the HTTP methods.' })).toHaveCount(1, { timeout: 60000 })
  await expect(page.locator('[data-role=assistant]').filter({ hasText: 'This is a longer explanation' })).toHaveCount(0)
  await expect(page.locator('[data-role=assistant]').last()).toContainText('Status codes describe the HTTP response.')
  console.log('PASS: phone 390x844; real chat admission with fake STT/TTS; live partial, final dedup, acknowledged prefix, barge-in flush, changed request same thread, truncated history after reload.')
}

/** PR #16: the live voice is the default; full duplex appears only when the server enables it,
 * and a refused speech edge falls back to the live voice. Real app/gateway/mode route; fake STT. */
/* global window */
export async function voiceModeFlow(page, expect, output) {
  const voice = page.getByRole('group', { name: 'Voice chat', exact: true })
  const continuous = page.getByLabel('Continuous voice')
  // The real server route, called through the app's own authenticated API client.
  const body = await page.evaluate(() => window.hermesDesktop.api({ path: '/api/aura/voice/mode' }))
  if (body?.full_duplex !== false || body?.enabled !== false) {
    throw new Error(`Default mode should be off, got ${JSON.stringify(body)}`)
  }
  await expect(page.getByRole('heading', { name: 'What are you working on?' })).toBeVisible({ timeout: 60000 })
  await expect(voice.getByRole('button', { name: 'Start voice chat' })).toBeVisible({ timeout: 60000 })
  // Trial click: passes only once nothing (the CONNECTING overlay) covers the control.
  await voice.getByRole('button', { name: 'Start voice chat' }).click({ trial: true, timeout: 60000 })
  await expect(continuous).toHaveCount(0)
  await page.screenshot({ path: `${output}/voice-default-mobile.png` })
  console.log(`PASS: real GET /api/aura/voice/mode -> ${JSON.stringify(body)}; composer shows the live voice, no continuous voice.`)

  await page.route('**/api/aura/voice/mode**', route => route.fulfill({ json: { full_duplex: true, enabled: true, runtime: true } }))
  const fixture = await installVoiceFixture(page)
  await page.reload()
  await expect(continuous).toBeVisible({ timeout: 60000 })
  await expect(voice).toHaveCount(0)
  await continuous.getByRole('button', { name: 'Voice', exact: true }).click()
  await expect.poll(() => fixture.connected).toBe(true)
  fixture.emit({ type: 'partial', turn_id: fixture.turn, text: 'What should I remember' })
  await expect(continuous).toContainText('What should I remember')
  for (let i = 0; i < 2; i++) { fixture.emit({ type: 'final', turn_id: fixture.turn, text: 'What should I remember from the brief?' }) }
  await expect(page.locator('[data-role=user]').filter({ hasText: 'What should I remember from the brief?' })).toHaveCount(1, { timeout: 60000 })
  await page.screenshot({ path: `${output}/voice-full-duplex-mobile.png` })
  console.log('PASS: with mode on (route-faked), continuous voice replaces it; a duplicated final is admitted once through the real chat.')

  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await page.route('**/api/aura/voice/mode**', route => route.fulfill({ json: { full_duplex: true, enabled: true, runtime: true } }))
  await page.routeWebSocket('**/api/audio/pipecat?**', ws => {
    ws.onMessage(raw => {
      if (JSON.parse(String(raw)).type === 'hello') { ws.send(JSON.stringify({ type: 'unavailable', epoch: 'x', seq: 1 })); ws.close() }
    })
  })
  await page.reload()
  await continuous.getByRole('button', { name: 'Voice', exact: true }).click()
  await expect(voice.getByRole('button', { name: 'Start voice chat' })).toBeVisible({ timeout: 60000 })
  await expect(continuous).toHaveCount(0)
  console.log('PASS: a refused speech edge falls back to the live voice (AuraVoice), not a bare control.')
}
