// Thin wrapper over WebLLM in a web worker. Everything here runs on the user's device: no Aura server
// call, no API key, no per-token bill. The weights (~290 MB) come once from Hugging Face and stay in the
// browser's Cache Storage until removed.
import type { WebWorkerMLCEngine } from '@mlc-ai/web-llm'

import type { LocalTurn } from './local-model'

/** Measured by WebLLM on this device for one reply (as mlc-ai/web-llm-chat shows under each message). */
export interface LocalReply {
  text: string
  finish: null | string
  decodeTps: null | number
  prefillTps: null | number
}

export interface LocalEngine {
  chat: (
    messages: LocalTurn[],
    onText: (text: string) => void,
    options?: { maxTokens?: number; temperature?: number }
  ) => Promise<LocalReply>
  stop: () => void
  dispose: () => void
}

export interface LocalEngineStart {
  ready: Promise<LocalEngine>
  cancel: () => void
}

export function startLocalEngine(modelId: string, onProgress: (fraction: number, text: string) => void): LocalEngineStart {
  const worker = new Worker(new URL('./local-engine.worker.ts', import.meta.url), { type: 'module' })
  let cancelled = false

  let reject: (error: Error) => void = () => {}

  const cancelledError = new Promise<never>((_, no) => {
    reject = no
  })

  const load = import('@mlc-ai/web-llm').then(({ CreateWebWorkerMLCEngine }) =>
    CreateWebWorkerMLCEngine(worker, modelId, {
      initProgressCallback: report => {
        if (!cancelled) {
          onProgress(report.progress, report.text)
        }
      }
    })
  )

  const ready = Promise.race([load, cancelledError]).then(
    (engine: WebWorkerMLCEngine) => wrap(engine, worker),
    error => {
      worker.terminate()
      throw error
    }
  )

  return {
    ready,
    cancel: () => {
      cancelled = true
      // Terminating the worker is the only way to stop a download or shader compile mid-way.
      worker.terminate()
      reject(new DOMException('Download cancelled', 'AbortError'))
    }
  }
}

function wrap(engine: WebWorkerMLCEngine, worker: Worker): LocalEngine {
  return {
    chat: async (messages, onText, options = {}) => {
      // No `tools` and no tool_choice: the on-device model has no way to call anything.
      const stream = await engine.chat.completions.create({
        messages,
        stream: true,
        stream_options: { include_usage: true },
        max_tokens: options.maxTokens ?? 160,
        temperature: options.temperature ?? 0.6
      })

      const reply: LocalReply = { text: '', finish: null, decodeTps: null, prefillTps: null }

      for await (const chunk of stream) {
        const choice = chunk.choices[0]

        if (choice?.delta?.content) {
          reply.text += choice.delta.content
          onText(reply.text)
        }

        reply.finish = choice?.finish_reason ?? reply.finish

        const extra = chunk.usage?.extra

        if (extra) {
          reply.decodeTps = extra.decode_tokens_per_s
          reply.prefillTps = extra.prefill_tokens_per_s
        }
      }

      return reply
    },
    stop: () => {
      engine.interruptGenerate()
    },
    dispose: () => {
      void engine.unload().catch(() => {})
      worker.terminate()
    }
  }
}

export async function isLocalModelCached(modelId: string): Promise<boolean> {
  const { hasModelInCache } = await import('@mlc-ai/web-llm')

  return hasModelInCache(modelId).catch(() => false)
}

export async function removeLocalModel(modelId: string): Promise<void> {
  const { deleteModelAllInfoInCache } = await import('@mlc-ai/web-llm')

  await deleteModelAllInfoInCache(modelId)
}
