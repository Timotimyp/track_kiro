/**
 * Lightweight hook that surfaces the user's Microsoft account + a cached
 * Graph access token. Returns no-op values when MSAL is not configured.
 *
 * Implementation notes:
 *
 * - We do NOT use `useAccount` from msal-react: it expects an
 *   `AccountIdentifiers` shape, not the full `AccountInfo` that
 *   `useMsal().accounts` produces. Passing it the wrong shape silently
 *   returns `null`, which is why the topbar appeared stuck on "Sign in"
 *   even after a successful login.
 *
 * - We also do NOT rely solely on `useMsal().accounts`. In practice that
 *   array doesn't always propagate into our render cycle in time — there
 *   are timing gaps between MSAL's internal cache and msal-react's React
 *   state, especially right after a redirect login. Instead we read the
 *   source of truth ourselves (`instance.getActiveAccount()` with a
 *   `getAllAccounts()` fallback) and subscribe to **every** MSAL event so
 *   any cache change triggers a refresh.
 *
 * - The MSAL cache lives in `sessionStorage` (see `auth.ts` for the
 *   reasoning). sessionStorage is per-tab, so we don't bother with a
 *   cross-tab `storage` listener — there is no cross-tab anyway.
 */
import {
  EventType,
  type AccountInfo,
  type AuthenticationResult,
  type EventMessage,
} from '@azure/msal-browser'
import { useMsal } from '@azure/msal-react'
import { useCallback, useEffect, useState } from 'react'
import {
  acquireGraphToken,
  GRAPH_SCOPES,
  isAzureConfigured,
  msalInstance,
} from './auth'

function pickInitialAccount(): AccountInfo | null {
  if (!isAzureConfigured() || !msalInstance) {
    console.log('[ms-auth] pickInitialAccount: not configured')
    return null
  }
  const active = msalInstance.getActiveAccount()
  const all = msalInstance.getAllAccounts()
  const picked = active ?? all[0] ?? null
  console.log(
    '[ms-auth] pickInitialAccount:',
    { active: !!active, allCount: all.length, pickedUsername: picked?.username ?? null },
  )
  return picked
}

export interface MicrosoftAuthState {
  enabled: boolean
  isSignedIn: boolean
  username: string | null
  displayName: string | null
  signIn: () => Promise<void>
  signOut: () => Promise<void>
  getToken: (scopes?: string[]) => Promise<string | null>
}

export function useMicrosoftAuth(): MicrosoftAuthState {
  const enabled = isAzureConfigured()
  const { instance } = useMsal()
  // Lazy initial state covers cold page loads where MSAL's sessionStorage
  // already contains an account (so the topbar shows the signed-in state on
  // first paint, not after a microtask).
  const [account, setAccount] = useState<AccountInfo | null>(pickInitialAccount)
  const [token, setToken] = useState<string | null>(null)

  // Keep `account` in sync with MSAL's internal cache via its event bus.
  useEffect(() => {
    if (!enabled) return

    function pickAccount(): AccountInfo | null {
      return instance.getActiveAccount() ?? instance.getAllAccounts()[0] ?? null
    }

    // Make sure the picked account is also "active" so silent token acquisition
    // works without prompting the user. Also write it back into our React
    // state — if pickInitialAccount returned null at useState() time (rare
    // race where MSAL hadn't hydrated yet) the lazy state would be stale
    // without this nudge.
    const initial = pickAccount()
    if (initial && !instance.getActiveAccount()) {
      instance.setActiveAccount(initial)
    }
    // We deliberately resync React state to MSAL's external cache on mount.
    // The lazy useState() initializer also reads from MSAL, but in rare races
    // (StrictMode double-mount, MSAL.initialize() finishing between the two)
    // the React state can lag — this catches it. The rule warns about
    // cascading renders, which we don't incur here because setAccount no-ops
    // when the value is the same reference.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAccount(initial)

    const callbackId = instance.addEventCallback((event: EventMessage) => {
      console.log('[ms-auth] MSAL event:', event.eventType)
      // Promote a freshly-acquired account to active so silent token requests
      // (e.g. for /me/calendarView) succeed without a popup.
      if (
        event.eventType === EventType.LOGIN_SUCCESS ||
        event.eventType === EventType.ACQUIRE_TOKEN_SUCCESS
      ) {
        const payload = event.payload as AuthenticationResult | null
        if (payload?.account) instance.setActiveAccount(payload.account)
      }
      if (event.eventType === EventType.LOGOUT_SUCCESS) {
        instance.setActiveAccount(null)
      }
      setAccount(pickAccount())
    })

    // When the tab is brought back into focus (e.g. user returned from
    // login.microsoftonline.com in a separate tab) recheck whether MSAL
    // has an account so the UI updates without a manual reload.
    function onVisibilityChange() {
      if (document.visibilityState === 'visible') setAccount(pickAccount())
    }
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      if (callbackId) instance.removeEventCallback(callbackId)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [enabled, instance])

  // Refresh the Graph token when the signed-in account changes.
  useEffect(() => {
    let cancelled = false
    if (!enabled || !account) {
      Promise.resolve().then(() => {
        if (!cancelled) setToken(null)
      })
      return () => {
        cancelled = true
      }
    }
    acquireGraphToken(account, GRAPH_SCOPES).then((t) => {
      if (!cancelled) setToken(t)
    })
    return () => {
      cancelled = true
    }
  }, [enabled, account])

  const signIn = useCallback(async () => {
    if (!enabled) return
    console.log('[ms-auth] starting loginRedirect with scopes', GRAPH_SCOPES)
    try {
      // loginRedirect navigates the current tab to login.microsoftonline.com
      // and back, so we never have to worry about cross-tab popups or browser
      // popup blockers — by the time main.tsx re-runs handleRedirectPromise(),
      // the account is already in MSAL's localStorage cache.
      await instance.loginRedirect({ scopes: GRAPH_SCOPES })
    } catch (err) {
      console.error('[ms-auth] Microsoft sign-in failed', err)
    }
  }, [enabled, instance])

  const signOut = useCallback(async () => {
    if (!enabled) return
    console.log('[ms-auth] starting logoutRedirect')
    try {
      await instance.logoutRedirect()
    } catch (err) {
      console.error('[ms-auth] Microsoft sign-out failed', err)
    } finally {
      setAccount(null)
    }
  }, [enabled, instance])

  const getToken = useCallback(
    async (scopes: string[] = GRAPH_SCOPES) => {
      if (!enabled || !account) return null
      if (scopes === GRAPH_SCOPES && token) return token
      return acquireGraphToken(account, scopes)
    },
    [enabled, account, token],
  )

  return {
    enabled,
    isSignedIn: enabled && !!account,
    username: account?.username ?? null,
    displayName: account?.name ?? account?.username ?? null,
    signIn,
    signOut,
    getToken,
  }
}
