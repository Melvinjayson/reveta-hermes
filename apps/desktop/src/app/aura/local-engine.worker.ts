// Runs WebLLM off the main thread so download, compile and generation never block the Aura UI.
import { WebWorkerMLCEngineHandler } from '@mlc-ai/web-llm'

const handler = new WebWorkerMLCEngineHandler()

self.onmessage = (event: MessageEvent) => handler.onmessage(event)
