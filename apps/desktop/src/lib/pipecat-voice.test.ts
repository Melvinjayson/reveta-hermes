import { afterEach, expect, it, vi } from 'vitest'

import { PipecatVoice } from './pipecat-voice'
vi.mock('./sibling-ws-url', () => ({ resolveSiblingWsUrl: vi.fn().mockResolvedValue('wss://fixture/api/audio/pipecat') }))
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
it('reconnects after its last sequence without replaying acknowledged audio', async () => {
  vi.useFakeTimers()
  const sockets: Socket[] = [], starts = vi.fn(), stops = vi.fn()

  class Socket {
    static OPEN = 1
    readyState = 1; bufferedAmount = 0
    onopen?: () => void
    onmessage?: (event: { data: string }) => void
    onclose?: (event: { code: number }) => void
    send = vi.fn(); close = vi.fn()
    constructor() { sockets.push(this) }
    emit(frame: object) { this.onmessage?.({ data: JSON.stringify(frame) }) }
  }

  class Context {
    currentTime = 0; destination = {}; audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) }
    resume = vi.fn().mockResolvedValue(undefined); close = vi.fn().mockResolvedValue(undefined)
    createMediaStreamSource = () => ({ connect: vi.fn() })
    createBuffer = () => ({ duration: 0.1, getChannelData: () => new Float32Array(2) })
    createBufferSource = () => ({ connect: vi.fn(), start: starts, stop: stops, onended: null })
  }
  vi.stubGlobal('WebSocket', Socket)
  vi.stubGlobal('AudioContext', Context)
  vi.stubGlobal('AudioWorkletNode', class { port = { onmessage: null, close: vi.fn() }; connect = vi.fn(); disconnect = vi.fn() })
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }) } })
  const event = vi.fn(), fail = vi.fn()
  const client = new PipecatVoice({}, 'same-chat', event, fail)
  await client.start()
  sockets[0].onopen?.()
  const packet = { type: 'audio', epoch: 'one', seq: 1, turn_id: 'turn', packet_id: 'sentence', pcm: 'AAAAAA==' }
  sockets[0].emit(packet)
  expect(starts).toHaveBeenCalledTimes(1)
  sockets[0].onclose?.({ code: 1006 })
  expect(stops).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(500)
  sockets[1].onopen?.()
  expect(JSON.parse(sockets[1].send.mock.calls[0][0])).toMatchObject({ conversation_id: 'same-chat', after_seq: 1 })
  sockets[1].emit(packet)
  sockets[1].emit({ ...packet, seq: 2 })
  expect(starts).toHaveBeenCalledTimes(1)
  expect(fail).not.toHaveBeenCalled()
  client.stop()
})
