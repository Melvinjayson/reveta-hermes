// @vitest-environment jsdom
// Loaded once at collection, outside every hook's budget: vi.resetModules() keeps each module's
// transformed code, so the fresh copy a test imports only re-evaluates it. Without this each
// host's hook pays the cold transform of the whole graph and times out on a loaded runner.
import '@/app/chat/sidebar'
import '@/app/shell/hooks/use-statusbar-items'
import '@/components/pane-shell/tree/model'
import '@/components/pane-shell/tree/store'
import '@/components/ui/sidebar'
import '@/store/profile-rail-prefs'

import { act, cleanup, render, renderHook } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

// Switching profiles has exactly one door at a time: the rail at the sidebar
// foot, or the statusbar picker beside the gateway switcher when the user hides
// the rail. The Webapp (browser-hosted Desktop) always draws the rail as its
// dropdown when the rail is available; Aura Simple mode shadows that rail
// preference. Native Desktop keeps the squares until the dropdown threshold.
// The host is fixed per page load, so each case loads a
// fresh module graph after declaring its host.

type SurfaceWindow = Window & { __HERMES_UI_SURFACE__?: string }

const noop = () => {}

const noopAsync = async () => {}

afterEach(() => {
  cleanup()
  localStorage.clear()
})

async function importHost(webapp: boolean) {
  if (webapp) {
    ;(window as SurfaceWindow).__HERMES_UI_SURFACE__ = 'webapp'
  }

  vi.resetModules()

  const [{ ChatSidebar }, { SidebarProvider }, { useStatusbarItems }, { group }, { $layoutTree }, prefs] =
    await Promise.all([
      import('@/app/chat/sidebar'),
      import('@/components/ui/sidebar'),
      import('@/app/shell/hooks/use-statusbar-items'),
      import('@/components/pane-shell/tree/model'),
      import('@/components/pane-shell/tree/store'),
      import('@/store/profile-rail-prefs')
    ])

  return { $layoutTree, ChatSidebar, group, prefs, SidebarProvider, useStatusbarItems }
}

type HostModules = Awaited<ReturnType<typeof importHost>>

function renderDoors({ $layoutTree, ChatSidebar, group, SidebarProvider, useStatusbarItems }: HostModules) {
  // The sessions pane is on screen: both doors live with it.
  $layoutTree.set(group(['sessions'], { active: 'sessions', id: 'sessions-group' }))

  const sidebar = render(
    <MemoryRouter>
      <SidebarProvider>
        <ChatSidebar
          currentView="chat"
          onArchiveSession={noop}
          onBranchSession={noop}
          onDeleteSession={noop}
          onLoadMoreSessions={noop}
          onManageCronJob={noop}
          onNavigate={noop}
          onNewSessionInWorkspace={noop}
          onNewSessionSplit={noop}
          onResumeSession={noop}
          onRetrySessions={noopAsync}
          onTriggerCronJob={noopAsync}
        />
      </SidebarProvider>
    </MemoryRouter>
  )

  const statusbar = renderHook(
    () =>
      useStatusbarItems({
        agentsOpen: false,
        changeSessionCwd: noopAsync,
        chatOpen: true,
        commandCenterOpen: false,
        extraLeftItems: [],
        extraRightItems: [],
        freshDraftReady: false,
        gatewayState: 'ready',
        inferenceStatus: null,
        openAgents: noop,
        openCommandCenterSection: noop,
        requestGateway: async () => undefined as never,
        statusSnapshot: null,
        toggleCommandCenter: noop
      }),
    { wrapper: MemoryRouter }
  )

  const doors = () => ({
    dropdown: sidebar.container.querySelector('[data-slot="profile-dropdown"]') !== null,
    picker: statusbar.result.current.leftStatusbarItems.some(item => item.id === 'profile-switcher' && !item.hidden),
    rail: sidebar.container.querySelector('[data-slot="profile-rail"]') !== null
  })

  return doors
}

describe.each([
  { host: 'Webapp', webapp: true },
  { host: 'native Desktop', webapp: false }
])('$host', ({ webapp }) => {
  let host: HostModules

  beforeAll(async () => {
    host = await importHost(webapp)
  })

  afterAll(() => {
    delete (window as SurfaceWindow).__HERMES_UI_SURFACE__
    vi.resetModules()
  })

  it('keeps one profile door with Simple as the Webapp default', () => {
    const doors = renderDoors(host)

    // Aura starts in Simple, which shadows the rail preference. Native Desktop
    // retains its Advanced default and the rail at the sidebar foot.
    expect(doors()).toEqual({ dropdown: false, picker: webapp, rail: !webapp })

    // An explicit toggle reverses the default: Aura reveals its dropdown;
    // native Desktop hides its rail and hands the door to the picker.
    act(() => host.prefs.toggleProfileRailVisible())
    expect(doors()).toEqual({ dropdown: webapp, picker: !webapp, rail: webapp })
  })
})
