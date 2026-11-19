import { useStore } from '@nanostores/react'
import { useEffect, useRef } from 'react'

import {
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator
} from '@/components/ui/dropdown-menu'
import { Wrench, X } from '@/lib/icons'

import {
  $auraCapabilities,
  $auraCapabilityError,
  $auraToolsOpen,
  AURA_MODE_HINTS,
  AURA_MODES,
  loadAuraCapabilities,
  setAuraMode,
  toggleAuraCapability
} from './capabilities'

/** Mode presets and the Tools entry inside the composer's + menu. */
export function AuraComposerMenuSection() {
  const status = useStore($auraCapabilities)

  useEffect(() => {
    if (!status) {
      void loadAuraCapabilities()
    }
  }, [status])

  return (
    <>
      <DropdownMenuSeparator />
      <DropdownMenuLabel className="px-2 pb-0.5 pt-0.5 text-[0.625rem] font-semibold uppercase tracking-wider text-(--ui-text-tertiary)">
        Mode for new chats
      </DropdownMenuLabel>
      <DropdownMenuRadioGroup onValueChange={mode => void setAuraMode(mode)} value={status?.mode ?? ''}>
        {AURA_MODES.map(mode => (
          <DropdownMenuRadioItem
            className="text-[length:var(--conversation-tool-font-size)]"
            disabled={!status}
            key={mode}
            value={mode}
          >
            <span className="grid">
              <span>{mode}</span>
              <span className="text-[0.7rem] text-(--ui-text-tertiary)">{AURA_MODE_HINTS[mode]}</span>
            </span>
          </DropdownMenuRadioItem>
        ))}
      </DropdownMenuRadioGroup>
      <DropdownMenuItem
        className="text-[length:var(--conversation-tool-font-size)] focus:bg-(--ui-bg-tertiary)"
        onSelect={() => $auraToolsOpen.set(true)}
      >
        <Wrench />
        <span>Tools…</span>
      </DropdownMenuItem>
    </>
  )
}

/** One switch per Hermes capability; key-less ones are shown switched off with the reason. */
export function AuraToolsDialog({ theme }: { theme: string }) {
  const open = useStore($auraToolsOpen)
  const status = useStore($auraCapabilities)
  const error = useStore($auraCapabilityError)
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const node = dialog.current

    if (open) {
      void loadAuraCapabilities()

      if (node && !node.open) {
        node.showModal()
      }
    } else if (node?.open) {
      node.close()
    }
  }, [open])

  const close = () => $auraToolsOpen.set(false)

  return (
    <dialog
      aria-labelledby="aura-tools-title"
      className="aura-dialog aura-tools-dialog"
      data-aura-theme={theme}
      onCancel={event => {
        event.preventDefault()
        close()
      }}
      onClick={event => event.target === dialog.current && close()}
      ref={dialog}
    >
      <header className="aura-dialog-header">
        <h2 id="aura-tools-title">Tools</h2>
        <button aria-label="Close tools" className="aura-icon-button" onClick={close} type="button">
          <X size={18} />
        </button>
      </header>
      <div className="aura-tools-body">
        <p className="aura-muted">
          Changes apply to new chats. Anything that changes something — sending, submitting, buying, deleting or
          running a command — still asks for your approval first.
        </p>
        {error && <p role="alert">{error}</p>}
        {!status && !error && <p role="status">Loading tools…</p>}
        {status && (
          <ul className="aura-tool-list">
            {status.capabilities.map(capability => (
              <li data-aura-capability={capability.id} key={capability.id}>
                <label>
                  <span className="aura-tool-text">
                    <span className="aura-tool-name">{capability.label}</span>
                    <span className="aura-muted">{capability.description}</span>
                    {capability.blocked && <span className="aura-tool-blocked">Not set up: {capability.blocked}</span>}
                  </span>
                  <input
                    checked={capability.enabled}
                    disabled={!capability.available}
                    onChange={event => void toggleAuraCapability(status, capability.id, event.target.checked)}
                    role="switch"
                    type="checkbox"
                  />
                </label>
              </li>
            ))}
          </ul>
        )}
      </div>
    </dialog>
  )
}
