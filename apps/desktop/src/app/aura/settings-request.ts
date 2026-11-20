import { atom } from 'nanostores'

import type { SETTINGS_SECTIONS } from './settings-dialog'

export type AuraSettingsSection = (typeof SETTINGS_SECTIONS)[number]

/** A control outside the shell asks for Settings open at one section; the shell clears it on close. */
export const $auraSettingsRequest = atom<AuraSettingsSection | null>(null)
