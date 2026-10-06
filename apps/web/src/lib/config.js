/**
 * Runtime configuration from Vite env vars (set in Vercel or apps/web/.env.local).
 *
 * VITE_API_BASE_URL unset  → demo mode: data stays in this browser (localStorage).
 * VITE_API_BASE_URL set    → connected mode: sign in, data lives in the SecurityOS API.
 *
 * VITE_AUTH_MODE = "entra" (default) | "dev"
 *   entra: Microsoft Entra External ID via MSAL
 *          VITE_ENTRA_CLIENT_ID, VITE_ENTRA_AUTHORITY, VITE_ENTRA_API_SCOPE
 *   dev:   local dev sign-in (API must run with ENV=dev; never in production)
 */
const env = import.meta.env;

export const API_BASE_URL = (env.VITE_API_BASE_URL || '').replace(/\/+$/, '');
export const IS_API_MODE = API_BASE_URL.length > 0;
export const AUTH_MODE = (env.VITE_AUTH_MODE || 'entra').toLowerCase();

export const ENTRA = {
  clientId: env.VITE_ENTRA_CLIENT_ID || '',
  authority: env.VITE_ENTRA_AUTHORITY || '',
  apiScope: env.VITE_ENTRA_API_SCOPE || '',
};

export function configProblems() {
  if (!IS_API_MODE) return [];
  const problems = [];
  if (AUTH_MODE === 'entra') {
    if (!ENTRA.clientId) problems.push('VITE_ENTRA_CLIENT_ID is not set');
    if (!ENTRA.authority) problems.push('VITE_ENTRA_AUTHORITY is not set');
    if (!ENTRA.apiScope) problems.push('VITE_ENTRA_API_SCOPE is not set');
  } else if (AUTH_MODE !== 'dev') {
    problems.push(`Unknown VITE_AUTH_MODE "${AUTH_MODE}" (use "entra" or "dev")`);
  }
  return problems;
}
