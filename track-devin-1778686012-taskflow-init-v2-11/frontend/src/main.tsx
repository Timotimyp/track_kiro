import { MsalProvider } from '@azure/msal-react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { msalInstance } from './auth'
import './styles.css'

const root = createRoot(document.getElementById('root')!)

if (msalInstance) {
  // Required by MSAL before any other API call. Resolves any redirect-based
  // login response that may be present in the URL after returning from
  // login.microsoftonline.com.
  const instance = msalInstance
  // Print a one-line summary of what auth state the browser is carrying
  // into this page load. Lets us tell at a glance whether a missing
  // username after F5 is "the cache was cleared" vs "the cache is there
  // but MSAL refused to read it".
  try {
    const sessKeys = Object.keys(sessionStorage).filter((k) => k.startsWith('msal'))
    const localKeys = Object.keys(localStorage).filter((k) => k.startsWith('msal'))
    console.log('[ms-auth] pre-init storage:', {
      sessionStorageMsalKeys: sessKeys,
      localStorageMsalKeys: localKeys,
      href: window.location.href,
    })
  } catch (e) {
    console.warn('[ms-auth] storage inspection failed', e)
  }
  instance
    .initialize()
    .then(() => instance.handleRedirectPromise())
    .then((result) => {
      console.log(
        '[ms-auth] handleRedirectPromise result:',
        result ? { username: result.account?.username ?? null } : 'no redirect response',
      )
      if (result?.account) instance.setActiveAccount(result.account)
    })
    .catch((err) => {
      console.error('[ms-auth] handleRedirectPromise failed', err)
    })
    .finally(() => {
      root.render(
        <StrictMode>
          <MsalProvider instance={instance}>
            <App />
          </MsalProvider>
        </StrictMode>,
      )
    })
} else {
  root.render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}
