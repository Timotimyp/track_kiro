/**
 * MSAL.js configuration for Azure AD (Entra ID) sign-in.
 *
 * - Uses the SPA "auth code with PKCE" flow — no client secret is needed,
 *   and the token never touches our backend except as an Authorization
 *   header that we forward to Microsoft Graph.
 * - `clientId` and `tenantId` are read from `VITE_AZURE_CLIENT_ID` and
 *   `VITE_AZURE_TENANT_ID`. When either is missing the app behaves exactly
 *   like before (no Sign in button, no calendar integration).
 *
 * Scopes (requested up front so users never see a second consent popup
 * after login):
 *   - `User.Read`           — read the signed-in user's profile (used for
 *                             the name in the topbar).
 *   - `Calendars.ReadWrite` — read AND write the user's Outlook calendar.
 *                             Read is needed for conflict detection; write
 *                             is needed when the user ticks
 *                             "Also add to my Outlook" in the task modal.
 *                             ReadWrite implies Read, so we don't need to
 *                             list both — listing both would only add
 *                             noise to the consent screen.
 */
import {
  InteractionRequiredAuthError,
  PublicClientApplication,
  type AccountInfo,
  type Configuration,
  type SilentRequest,
} from '@azure/msal-browser'

export const AZURE_CLIENT_ID = import.meta.env.VITE_AZURE_CLIENT_ID as string | undefined
export const AZURE_TENANT_ID =
  (import.meta.env.VITE_AZURE_TENANT_ID as string | undefined) || 'common'

/**
 * One set of scopes covers both reading conflicts and writing new events.
 * Microsoft treats `Calendars.ReadWrite` as a superset of `Calendars.Read`,
 * so a single consent is enough — no incremental popup later.
 */
export const GRAPH_SCOPES = ['User.Read', 'Calendars.ReadWrite']

/** @deprecated kept for backwards compat — use GRAPH_SCOPES. */
export const GRAPH_READ_SCOPES = GRAPH_SCOPES
/** @deprecated kept for backwards compat — use GRAPH_SCOPES. */
export const GRAPH_WRITE_SCOPES = GRAPH_SCOPES

export function isAzureConfigured(): boolean {
  return !!AZURE_CLIENT_ID && AZURE_CLIENT_ID.length > 0
}

export function buildMsalConfig(): Configuration | null {
  if (!isAzureConfigured()) return null
  return {
    auth: {
      clientId: AZURE_CLIENT_ID as string,
      authority: `https://login.microsoftonline.com/${AZURE_TENANT_ID}`,
      redirectUri: window.location.origin,
      postLogoutRedirectUri: window.location.origin,
    },
    cache: {
      // sessionStorage so the signed-in account survives F5 / Cmd+R but
      // not browser/tab close. We tried `localStorage` first, but MSAL 4+
      // encrypts the cached account with an AES key it keeps in a session
      // cookie (`msal.cache.encryption`, Secure + SameSite=None). On
      // `http://localhost` that cookie is not always persisted (and
      // strict cookie/privacy settings can drop it across navigations
      // too), and when the encrypted blob can't be decrypted MSAL purges
      // the account from its cache — which surfaced as "login disappears
      // on refresh". sessionStorage stores the account in plaintext and
      // is read directly by MSAL on init, with no cookie dependency.
      cacheLocation: 'sessionStorage',
      // We don't need the encryption cookie at all, but keep its Secure
      // flag off so anything else MSAL writes to cookies works on http
      // localhost without silent drops.
      secureCookies: false,
    },
  }
}

/** Storage key that MSAL writes when its account cache changes. */
export const MSAL_ACCOUNT_KEYS_STORAGE_KEY = 'msal.account.keys'

export const msalInstance: PublicClientApplication | null = (() => {
  const cfg = buildMsalConfig()
  return cfg ? new PublicClientApplication(cfg) : null
})()

/**
 * Acquire a Graph access token silently.
 *
 * Because we request the full set of scopes (User.Read + Calendars.ReadWrite)
 * at login time, this should always succeed silently — the cached refresh
 * token already covers everything we'll ever need.
 *
 * If silent acquisition fails AND the failure is "the user must interact"
 * (e.g. they revoked consent in the Microsoft portal, or the cached refresh
 * token expired), we navigate to `loginRedirect` so the user re-consents.
 * For any other failure (transient network, etc.) we return null and let the
 * caller surface a toast.
 */
export async function acquireGraphToken(
  account: AccountInfo,
  scopes: string[] = GRAPH_SCOPES,
): Promise<string | null> {
  if (!msalInstance) return null
  const request: SilentRequest = { account, scopes }
  try {
    const result = await msalInstance.acquireTokenSilent(request)
    return result.accessToken
  } catch (err) {
    if (err instanceof InteractionRequiredAuthError) {
      console.warn('[ms-auth] silent token requires interaction, redirecting', err)
      try {
        await msalInstance.loginRedirect({ scopes })
      } catch (loginErr) {
        console.error('[ms-auth] loginRedirect fallback also failed', loginErr)
      }
      return null
    }
    console.warn('[ms-auth] acquireTokenSilent failed (non-interactive)', err)
    return null
  }
}
