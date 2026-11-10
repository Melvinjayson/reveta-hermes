import { createContext } from 'react'

export const AuraReadiness = createContext<boolean | null>(null)
export const AuraContinueLater = createContext<(() => void) | null>(null)
