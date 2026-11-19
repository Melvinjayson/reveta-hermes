import { useStore } from '@nanostores/react'
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  Download,
  FileText,
  Globe,
  ListChecks,
  LoaderCircle,
  Search,
  SquareTerminal
} from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import { sessionFileOwnerScope } from '@/api/client'
import { dataUrlToBlob, MarkdownPreview } from '@/app/chat/right-rail/preview-file'
import { chatMessageText } from '@/lib/chat-messages'
import { readDesktopFileDataUrl, readDesktopFileText } from '@/lib/desktop-fs'
import { X } from '@/lib/icons'
import { downloadGatewayFileWithFeedback } from '@/lib/media'
import { $backgroundStatusBySession } from '@/store/composer-status'
import { $activeSessionId, $messages, $selectedStoredSessionId } from '@/store/session'
import { $subagentsBySession, type SubagentProgress } from '@/store/subagents'

import { auraFiles } from './files'
import { sourceHost } from './message-sources'
import { $auraPanel, type AuraPanelTab, clock, closeAuraPanel, previewKind } from './panel-store'
import { auraSources } from './sources'
import { type AuraStep, auraSteps, type StepStatus } from './steps'

const TABS: { id: AuraPanelTab; label: string }[] = [
  { id: 'work', label: 'Work' },
  { id: 'sources', label: 'Sources' },
  { id: 'files', label: 'Files' }
]

/** Plain-language state for each step status; the raw status stays on data-aura-step for tests. */
export const STEP_STATE: Record<StepStatus, { word: string; tone: 'pending' | 'active' | 'done' | 'problem' }> = {
  Queued: { word: 'Pending', tone: 'pending' },
  Running: { word: 'Working', tone: 'active' },
  Done: { word: 'Done', tone: 'done' },
  'Result received': { word: 'Finished', tone: 'done' },
  Unconfirmed: { word: 'Not confirmed', tone: 'pending' },
  Failed: { word: 'Failed', tone: 'problem' },
  Stopped: { word: 'Stopped', tone: 'problem' },
  Refused: { word: 'Not run', tone: 'problem' }
}

function stepIcon(step: AuraStep) {
  const tool = step.tool ?? ''

  if (/browser|fetch|web_/.test(tool)) {
    return Globe
  }

  if (/terminal|computer|process|execute_code/.test(tool)) {
    return SquareTerminal
  }

  if (/file|patch/.test(tool)) {
    return FileText
  }

  if (/search/.test(tool)) {
    return Search
  }

  if (tool === 'delegate_task') {
    return Bot
  }

  return ListChecks
}

function stateIcon(tone: string) {
  return tone === 'done' ? CheckCircle2 : tone === 'active' ? LoaderCircle : tone === 'problem' ? CircleAlert : CircleDashed
}

function useNow(running: boolean) {
  const [now, setNow] = useState(() => Date.now() / 1000)

  useEffect(() => {
    if (!running) {
      return
    }

    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000)

    return () => window.clearInterval(timer)
  }, [running])

  return now
}

/** m:ss from the backend's own timestamps; empty when timing was not recorded. */
export function stepElapsed(step: AuraStep, now: number) {
  if (step.timestamp === undefined) {
    return ''
  }

  const end = step.completedAt ?? (step.status === 'Running' ? now : undefined)

  return end === undefined ? '' : clock(end - step.timestamp)
}

function StepRow({ step, now }: { step: AuraStep; now: number }) {
  const state = STEP_STATE[step.status]
  const Icon = stepIcon(step)
  const StateIcon = stateIcon(state.tone)
  const time = stepElapsed(step, now)
  const detail = step.detail?.command || step.detail?.summary

  return (
    <li className="aura-work-step" data-aura-step={step.status} data-tone={state.tone}>
      <span aria-hidden="true" className="aura-work-icon">
        <Icon size={16} />
      </span>
      <div className="aura-work-main">
        <div className="aura-work-line">
          <span className="aura-work-label">{step.label}</span>
          {time && <time className="aura-work-time">{time}</time>}
        </div>
        <span className="aura-work-state">
          <StateIcon aria-hidden="true" size={13} />
          {state.word}
        </span>
        {step.detail?.url && (
          <a className="aura-work-link" href={step.detail.url} rel="noreferrer" target="_blank">
            {step.detail.url}
          </a>
        )}
        {step.status === 'Refused' &&
          step.facts
            .filter(fact => fact !== 'A result was received.')
            .map(fact => (
              <p className="aura-work-note" key={fact}>
                {fact}
              </p>
            ))}
        {(detail || step.status !== 'Refused') && (
          <details className="aura-work-details">
            <summary>Details</summary>
            {detail && <pre>{detail}</pre>}
            {step.status !== 'Refused' &&
              step.facts.map(fact => (
                <p className="aura-work-note" key={fact}>
                  {fact}
                </p>
              ))}
          </details>
        )}
      </div>
    </li>
  )
}

export function AuraStepList({ steps, now = Date.now() / 1000 }: { steps: AuraStep[]; now?: number }) {
  return (
    <ol className="aura-work-list aura-steps">
      {steps.map(step => (
        <StepRow key={step.id} now={now} step={step} />
      ))}
    </ol>
  )
}

function SubagentRow({ agent }: { agent: SubagentProgress }) {
  const tone = agent.status === 'completed' ? 'done' : agent.status === 'running' ? 'active' : agent.status === 'queued' ? 'pending' : 'problem'
  const StateIcon = stateIcon(tone)
  const word = { completed: 'Done', failed: 'Failed', interrupted: 'Stopped', queued: 'Pending', running: 'Working' }[agent.status]

  return (
    <li className="aura-work-step" data-aura-subagent={agent.status} data-tone={tone}>
      <span aria-hidden="true" className="aura-work-icon">
        <Bot size={16} />
      </span>
      <div className="aura-work-main">
        <span className="aura-work-label">{agent.goal || 'Subagent'}</span>
        <span className="aura-work-state">
          <StateIcon aria-hidden="true" size={13} />
          {word}
          {agent.currentTool ? ` · ${agent.currentTool}` : ''}
          {agent.durationSeconds !== undefined ? ` · ${clock(agent.durationSeconds)}` : ''}
        </span>
        {agent.summary && <p className="aura-work-note">{agent.summary.slice(0, 400)}</p>}
      </div>
    </li>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="aura-panel-section">
      <h3 className="aura-section-label">{title}</h3>
      {children}
    </section>
  )
}

function WorkTab() {
  const messages = useStore($messages)
  const runtimeId = useStore($activeSessionId)
  const subagents = useStore($subagentsBySession)[runtimeId ?? ''] ?? []
  const background = useStore($backgroundStatusBySession)[runtimeId ?? ''] ?? []
  const steps = auraSteps(messages)
  const running = steps.some(step => step.status === 'Running') || subagents.some(agent => agent.status === 'running')
  const now = useNow(running)

  if (!steps.length && !subagents.length && !background.length) {
    return (
      <p className="aura-empty-note">
        Nothing has run in this chat yet. When Aura uses a tool, each step appears here with its status and time.
        Anything that changes something asks for your approval in the chat first.
      </p>
    )
  }

  return (
    <>
      <p aria-live="polite" className="sr-only" role="status">
        {steps.length} steps, {steps.filter(step => step.status === 'Running').length} running.
      </p>
      {steps.length > 0 && (
        <Section title="Steps">
          <AuraStepList now={now} steps={steps} />
        </Section>
      )}
      {subagents.length > 0 && (
        <Section title="Subagents">
          <ul className="aura-work-list">
            {subagents.map(agent => (
              <SubagentRow agent={agent} key={agent.id} />
            ))}
          </ul>
        </Section>
      )}
      {background.length > 0 && (
        <Section title="Background tasks">
          <ul className="aura-work-list">
            {background.map(item => (
              <li className="aura-work-step" data-aura-background={item.state} key={item.id}>
                <span aria-hidden="true" className="aura-work-icon">
                  <SquareTerminal size={16} />
                </span>
                <div className="aura-work-main">
                  <span className="aura-work-label">{item.title}</span>
                  <span className="aura-work-state">{item.state}</span>
                  {item.output && <pre className="aura-work-output">{item.output.slice(-2000)}</pre>}
                </div>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </>
  )
}

function SourcesTab() {
  const messages = useStore($messages)
  const sources = auraSources(messages.filter(m => m.role === 'assistant').map(chatMessageText).join('\n'))

  if (!sources.length) {
    return <p className="aura-empty-note">Links Aura cites in this chat will be listed here.</p>
  }

  return (
    <ol className="aura-source-list">
      {sources.map(([url, label], index) => (
        <li data-aura-card="source" key={url}>
          <span aria-hidden="true" className="aura-source-number">
            {index + 1}
          </span>
          <a href={url} rel="noreferrer" target="_blank">
            <span className="aura-source-list-title">{label}</span>
            <span className="aura-source-host">{sourceHost(url)}</span>
          </a>
        </li>
      ))}
    </ol>
  )
}

interface PreviewState {
  status: 'idle' | 'loading' | 'ready' | 'error'
  text?: string
  src?: string
}

function FilePreview({ path, name, sessionId }: { path: string; name: string; sessionId?: string }) {
  const kind = previewKind(name)
  const [state, setState] = useState<PreviewState>({ status: 'idle' })

  useEffect(() => {
    let live = true

    if (kind === 'none') {
      return
    }

    setState({ status: 'loading' })

    const read =
      kind === 'text'
        ? readDesktopFileText(path, { sessionId }).then(result => ({ text: result.text }))
        : readDesktopFileDataUrl(path, { sessionId }).then(src => ({ src }))

    let objectUrl = ''

    read
      .then(result => {
        if (!live) {
          return
        }

        // PDFs render from a validated blob: Chrome's viewer refuses data: URLs in frames.
        if (kind === 'pdf' && 'src' in result && result.src) {
          objectUrl = URL.createObjectURL(dataUrlToBlob(result.src))
          setState({ status: 'ready', src: objectUrl })
        } else {
          setState({ status: 'ready', ...result })
        }
      })
      .catch(() => live && setState({ status: 'error' }))

    return () => {
      live = false

      if (objectUrl) {
        URL.revokeObjectURL(objectUrl)
      }
    }
  }, [kind, path, sessionId])

  if (kind === 'none') {
    return <p className="aura-empty-note">No preview for this file type. Download it to open it.</p>
  }

  if (state.status === 'loading' || state.status === 'idle') {
    return <p className="aura-empty-note" role="status">Loading preview…</p>
  }

  if (state.status === 'error') {
    return (
      <p className="aura-empty-note" role="alert">
        The preview couldn’t load (the file may be too large or no longer on the server). Download still works.
      </p>
    )
  }

  if (kind === 'text') {
    return /\.md$/i.test(name) ? (
      <div className="aura-file-markdown">
        <MarkdownPreview filePath={path} text={state.text ?? ''} />
      </div>
    ) : (
      <pre className="aura-file-text">{state.text}</pre>
    )
  }

  if (kind === 'image') {
    return <img alt={name} className="aura-file-image" src={state.src} />
  }

  return <iframe className="aura-file-pdf" src={state.src} title={`Preview of ${name}`} />
}

function FilesTab() {
  const messages = useStore($messages)
  const active = useStore($activeSessionId)
  const stored = useStore($selectedStoredSessionId)
  const sessionId = stored ?? active ?? undefined
  const owner = sessionId ? (sessionFileOwnerScope(sessionId) ?? undefined) : undefined
  const files = [...new Map(auraFiles(messages).map(file => [file.path, file])).values()]
  const [open, setOpen] = useState<null | string>(null)
  const current = files.find(file => file.path === open)

  if (!files.length) {
    return <p className="aura-empty-note">Files Aura creates in this chat will appear here, with a preview.</p>
  }

  return (
    <>
      <ul className="aura-file-list">
        {files.map(file => (
          <li data-aura-card="file" data-current={file.path === open || undefined} key={file.path}>
            <button className="aura-file-open" onClick={() => setOpen(file.path === open ? null : file.path)} type="button">
              <FileText aria-hidden="true" size={16} />
              <span className="aura-file-name">{file.name}</span>
              <span className="aura-muted">{file.bytes} bytes</span>
            </button>
            <button
              aria-label={`Download ${file.name}`}
              className="aura-icon-button"
              onClick={() =>
                void downloadGatewayFileWithFeedback(file.path, { sessionId, owner, suggestedName: file.name })
              }
              type="button"
            >
              <Download aria-hidden="true" size={16} />
            </button>
          </li>
        ))}
      </ul>
      {current && (
        <div aria-label={`Preview of ${current.name}`} className="aura-file-preview" role="region">
          <FilePreview name={current.name} path={current.path} sessionId={sessionId} />
        </div>
      )}
    </>
  )
}

/** Desktop: a column beside the thread. Phone: a full sheet (native modal dialog). */
export function AuraSidePanel({ wide, theme }: { wide: boolean; theme: string }) {
  const tab = useStore($auraPanel)
  const sheet = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const node = sheet.current

    if (!wide && tab && node && !node.open) {
      node.showModal()
    }

    if ((wide || !tab) && node?.open) {
      node.close()
    }
  }, [tab, wide])

  const body = tab && (
    <>
      <header className="aura-panel-header">
        <div aria-label="Side panel" className="aura-panel-tabs" role="tablist">
          {TABS.map(item => (
            <button
              aria-selected={tab === item.id}
              key={item.id}
              onClick={() => $auraPanel.set(item.id)}
              role="tab"
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
        <button aria-label="Close panel" className="aura-icon-button" onClick={closeAuraPanel} type="button">
          <X size={18} />
        </button>
      </header>
      <div className="aura-panel-body" role="tabpanel">
        {tab === 'work' && <WorkTab />}
        {tab === 'sources' && <SourcesTab />}
        {tab === 'files' && <FilesTab />}
      </div>
    </>
  )

  if (wide) {
    return tab ? (
      <aside aria-label="Work, sources and files" className="aura-side-panel">
        {body}
      </aside>
    ) : null
  }

  return (
    <dialog
      aria-label="Work, sources and files"
      className="aura-dialog aura-panel-sheet"
      data-aura-theme={theme}
      onCancel={event => {
        event.preventDefault()
        closeAuraPanel()
      }}
      ref={sheet}
    >
      {body}
    </dialog>
  )
}

