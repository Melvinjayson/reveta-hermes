import { webappSessionKey } from '@/lib/browser-launch-session'
import type { BrowserHostGlobals } from '@/lib/platform'

/** End this browser's existing grant; cookie-gated hosts use the existing logout flow. */
export async function auraSignOut() {
  const host = window as Window & BrowserHostGlobals

  if (!host.__HERMES_AUTH_REQUIRED__ && host.__HERMES_UI_SURFACE__ === 'webapp') {
    sessionStorage.removeItem(webappSessionKey(host.__HERMES_BASE_PATH__ || ''))
    window.location.reload()

    return
  }

  await window.hermesDesktop!.oauthLogoutConnectionConfig(window.location.origin)
}
