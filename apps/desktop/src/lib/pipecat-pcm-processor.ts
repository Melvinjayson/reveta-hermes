// Speech edge input: mono PCM at 16 kHz. Output is silent, including during TTS.
declare abstract class AudioWorkletProcessor { readonly port: MessagePort }
declare const sampleRate: number

declare function registerProcessor(name: string, processor: typeof AudioWorkletProcessor): void
class PipecatInput extends AudioWorkletProcessor {
  private phase = 0
  private samples: number[] = []
  process(inputs: Float32Array[][]): boolean {
    for (const sample of inputs[0]?.[0] ?? []) {
      this.phase += 16000

      if (this.phase >= sampleRate) {
        this.phase -= sampleRate
        this.samples.push(Math.round(Math.max(-1, Math.min(1, sample)) * 32767))

        if (this.samples.length === 320) {
          const pcm = new Int16Array(this.samples)
          this.port.postMessage(pcm.buffer, [pcm.buffer])
          this.samples = []
        }
      }
    }

    return true
  }
}
registerProcessor('aura-pipecat-input', PipecatInput)
export {}
