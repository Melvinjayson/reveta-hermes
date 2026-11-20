import { useEffect, useRef, useState } from 'react'

import { X } from '@/lib/icons'

import { AuraModelSettings } from './model-settings'
import {
  AuraConnectorsSection,
  AuraJobsSection,
  AuraMemorySection,
  AuraPreviewSection,
  AuraSkillsSection,
  AuraVoiceModeSetting
} from './settings-sections'

export const SETTINGS_SECTIONS = ['Appearance', 'Model', 'Memory', 'Skills', 'Scheduled jobs', 'Connectors', 'Voice', 'Preview', 'Account'] as const
type Section = (typeof SETTINGS_SECTIONS)[number]
type Mode = 'light' | 'dark' | 'system'

interface AuraSettingsDialogProps {
  open: boolean
  mode: Mode
  theme: string
  onMode: (mode: Mode) => void
  onClose: () => void
  onSignOut: () => void
  signOutError: string
}

export function AuraSettingsDialog({ open, mode, theme, onMode, onClose, onSignOut, signOutError }: AuraSettingsDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [section, setSection] = useState<Section>('Appearance')

  useEffect(() => {
    const node = dialog.current

    if (open && node && !node.open) {
      node.showModal()
    }

    if (!open && node?.open) {
      node.close()
    }
  }, [open])

  return (
    <dialog
      aria-labelledby="aura-settings-title"
      className="aura-dialog aura-settings-dialog"
      data-aura-theme={theme}
      onCancel={event => {
        event.preventDefault()
        onClose()
      }}
      onClick={event => event.target === dialog.current && onClose()}
      ref={dialog}
    >
      <header className="aura-dialog-header">
        <h2 id="aura-settings-title">Settings</h2>
        <button aria-label="Close settings" className="aura-icon-button" onClick={onClose} type="button">
          <X size={18} />
        </button>
      </header>
      <div className="aura-settings-layout">
        <nav aria-label="Settings sections" className="aura-settings-nav">
          {SETTINGS_SECTIONS.map(name => (
            <button
              aria-current={section === name ? 'page' : undefined}
              key={name}
              onClick={() => setSection(name)}
              type="button"
            >
              {name}
            </button>
          ))}
        </nav>
        <div className="aura-settings-body">
          {section === 'Appearance' && (
            <section aria-labelledby="aura-settings-appearance">
              <h3 id="aura-settings-appearance">Appearance</h3>
              <label className="aura-field">
                <span>Theme</span>
                <select onChange={event => onMode(event.target.value as Mode)} value={mode}>
                  <option value="light">Light</option>
                  <option value="dark">Dark</option>
                  <option value="system">Follow device</option>
                </select>
              </label>
            </section>
          )}
          {section === 'Model' && (
            <section aria-labelledby="aura-settings-model" className="aura-settings">
              <h3 id="aura-settings-model">Model</h3>
              <AuraModelSettings />
            </section>
          )}
          {section === 'Memory' && <AuraMemorySection />}
          {section === 'Skills' && <AuraSkillsSection />}
          {section === 'Scheduled jobs' && <AuraJobsSection />}
          {section === 'Connectors' && <AuraConnectorsSection />}
          {section === 'Preview' && <AuraPreviewSection />}
          {section === 'Voice' && (
            <section aria-labelledby="aura-settings-voice">
              <h3 id="aura-settings-voice">Voice</h3>
              <dl className="aura-definitions">
                <dt>Dictation</dt>
                <dd>
                  The microphone in the message box types what you say into your draft. It uses your browser’s speech
                  recognition and appears only when your browser supports it. Nothing is sent until you press Send.
                </dd>
                <dt>Voice chat</dt>
                <dd>
                  The Voice chat button starts a spoken conversation in this chat. Replies are spoken back; you can mute,
                  stop Aura speaking, or end it at any time. Your words and Aura’s replies are saved in the chat as text.
                </dd>
              </dl>
              <AuraVoiceModeSetting />
            </section>
          )}
          {section === 'Account' && (
            <section aria-labelledby="aura-settings-account">
              <h3 id="aura-settings-account">Account</h3>
              <p>Signing out ends this browser’s access. Conversation recovery after a server restart depends on durable server storage.</p>
              <button className="aura-button aura-button-secondary" onClick={onSignOut} type="button">
                Sign out
              </button>
              {signOutError && <p role="alert">{signOutError}</p>}
              <p className="aura-muted">Aura by Reveta</p>
            </section>
          )}
        </div>
      </div>
    </dialog>
  )
}
