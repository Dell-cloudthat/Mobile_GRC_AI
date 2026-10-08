/**
 * SecurityOS API client. Every call carries the signed-in user's token; the
 * server decides what they may do. Errors surface the server's own message.
 */
import { API_BASE_URL } from './config';
import { getAccessToken } from './auth';
import { ApiError } from './errors';

export { ApiError, errorMessage } from './errors';

const BASE = `${API_BASE_URL}/api/v1/securityos`;

async function request(method, path, body) {
  const token = await getAccessToken();
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? res.statusText);
  return data;
}

const org = id => `/organizations/${encodeURIComponent(id)}`;

export const api = {
  me: () => request('GET', '/me'),

  // Organizations
  createOrg: body => request('POST', '/organizations', body),
  createMspOrg: (mspId, body) => request('POST', `/msp/${encodeURIComponent(mspId)}/orgs`, body),
  deleteMspOrg: (mspId, orgId) => request('DELETE', `/msp/${encodeURIComponent(mspId)}/orgs/${encodeURIComponent(orgId)}`),
  getProfile: orgId => request('GET', `${org(orgId)}/profile`),
  saveProfile: (orgId, body) => request('POST', `${org(orgId)}/profile`, body),

  // Control state
  statuses: orgId => request('GET', `${org(orgId)}/statuses`),
  setStatus: (orgId, controlId, status, notes) =>
    request('PATCH', `${org(orgId)}/statuses`, { control_id: controlId, status, notes: notes ?? null }),

  // Findings
  findings: (orgId, controlId) =>
    request('GET', `${org(orgId)}/findings${controlId ? `?control_id=${encodeURIComponent(controlId)}` : ''}`),
  createFinding: (orgId, body) => request('POST', `${org(orgId)}/findings`, body),
  transition: (orgId, findingId, body) =>
    request('POST', `${org(orgId)}/findings/${encodeURIComponent(findingId)}/transition`, body),
  assignees: orgId => request('GET', `${org(orgId)}/assignees`),

  // Attestations
  attestations: orgId => request('GET', `${org(orgId)}/attestations?include_expired=true`),
  createAttestation: (orgId, body) => request('POST', `${org(orgId)}/attestations`, body),

  // Team
  members: orgId => request('GET', `${org(orgId)}/members`),
  removeMember: (orgId, userId) => request('DELETE', `${org(orgId)}/members/${encodeURIComponent(userId)}`),
  invites: orgId => request('GET', `${org(orgId)}/invites`),
  createInvite: (orgId, body) => request('POST', `${org(orgId)}/invites`, body),
  revokeInvite: (orgId, inviteId) => request('DELETE', `${org(orgId)}/invites/${encodeURIComponent(inviteId)}`),
  acceptInvite: token => request('POST', '/invites/accept', { token }),

  // Audit
  auditVerify: orgId => request('GET', `${org(orgId)}/audit/verify`),

  // Shadow AI
  aiApps: orgId => request('GET', `${org(orgId)}/ai-apps`),
  aiApp: (orgId, appKey) => request('GET', `${org(orgId)}/ai-apps/${encodeURIComponent(appKey)}`),
  importAiApps: (orgId, csvText, filename) =>
    request('POST', `${org(orgId)}/ai-apps/import`, { csv_text: csvText, filename }),
  decideAiApp: (orgId, appKey, body) =>
    request('POST', `${org(orgId)}/ai-apps/${encodeURIComponent(appKey)}/decision`, body),
  mspAiUsage: mspId => request('GET', `/msp/${encodeURIComponent(mspId)}/ai-usage`),
};

// ── Profile field mapping (API snake_case ↔ app camelCase) ────────────────────

export function profileFromApi(p = {}) {
  return {
    businessName: p.business_name ?? '',
    industry: p.industry ?? '',
    employeeCount: p.employee_count ?? '',
    emailProvider: p.email_provider ?? '',
    cloudProviders: p.cloud_providers ?? [],
    sensitiveData: p.sensitive_data ?? [],
  };
}

export function profileToApi(p = {}) {
  return {
    business_name: p.businessName || 'My Business',
    industry: p.industry ?? '',
    employee_count: p.employeeCount ?? '',
    email_provider: p.emailProvider ?? '',
    cloud_providers: p.cloudProviders ?? [],
    sensitive_data: p.sensitiveData ?? [],
  };
}
