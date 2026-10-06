/**
 * Sign-in for connected mode.
 *
 * Entra External ID (production): MSAL redirect flow with PKCE. MSAL keeps its
 * token cache in sessionStorage (cleared when the tab closes); access tokens
 * are never written to localStorage by this app.
 *
 * Dev (local only): asks the API's /dev/token endpoint, which exists only when
 * the API runs with ENV=dev. The token is kept in sessionStorage for reloads.
 */
import { PublicClientApplication, InteractionRequiredAuthError } from '@azure/msal-browser';
import { API_BASE_URL, AUTH_MODE, ENTRA } from './config';

const DEV_TOKEN_KEY = 'securityos_dev_token';
const DEV_USER_KEY = 'securityos_dev_user';

let msal = null;

async function getMsal() {
  if (msal) return msal;
  msal = new PublicClientApplication({
    auth: {
      clientId: ENTRA.clientId,
      authority: ENTRA.authority,
      knownAuthorities: [new URL(ENTRA.authority).hostname],
      redirectUri: window.location.origin,
      postLogoutRedirectUri: window.location.origin,
    },
    cache: { cacheLocation: 'sessionStorage' },
  });
  await msal.initialize();
  const result = await msal.handleRedirectPromise();
  if (result?.account) msal.setActiveAccount(result.account);
  if (!msal.getActiveAccount()) {
    const [first] = msal.getAllAccounts();
    if (first) msal.setActiveAccount(first);
  }
  return msal;
}

/** Resolve the signed-in user, or null. Also completes a pending redirect. */
export async function initAuth() {
  if (AUTH_MODE === 'dev') {
    const user = sessionStorage.getItem(DEV_USER_KEY);
    return sessionStorage.getItem(DEV_TOKEN_KEY) && user ? JSON.parse(user) : null;
  }
  const app = await getMsal();
  const account = app.getActiveAccount();
  return account ? { name: account.name, username: account.username } : null;
}

export async function signIn(devUser) {
  if (AUTH_MODE === 'dev') {
    const res = await fetch(`${API_BASE_URL}/api/v1/securityos/dev/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(devUser),
    });
    if (!res.ok) throw new Error('Dev sign-in failed. Is the API running with ENV=dev?');
    const { access_token } = await res.json();
    sessionStorage.setItem(DEV_TOKEN_KEY, access_token);
    sessionStorage.setItem(DEV_USER_KEY, JSON.stringify({ name: devUser.name || devUser.user_id, username: devUser.user_id }));
    return;
  }
  const app = await getMsal();
  await app.loginRedirect({ scopes: [ENTRA.apiScope, 'openid', 'offline_access'] });
}

export async function signOut() {
  if (AUTH_MODE === 'dev') {
    sessionStorage.removeItem(DEV_TOKEN_KEY);
    sessionStorage.removeItem(DEV_USER_KEY);
    window.location.reload();
    return;
  }
  const app = await getMsal();
  await app.logoutRedirect({ account: app.getActiveAccount() });
}

/** Access token for the API (refreshes silently; redirects to sign in if needed). */
export async function getAccessToken() {
  if (AUTH_MODE === 'dev') return sessionStorage.getItem(DEV_TOKEN_KEY);
  const app = await getMsal();
  const account = app.getActiveAccount();
  if (!account) return null;
  try {
    const result = await app.acquireTokenSilent({ scopes: [ENTRA.apiScope], account });
    return result.accessToken;
  } catch (err) {
    if (err instanceof InteractionRequiredAuthError) {
      await app.acquireTokenRedirect({ scopes: [ENTRA.apiScope], account });
      return null;
    }
    throw err;
  }
}
