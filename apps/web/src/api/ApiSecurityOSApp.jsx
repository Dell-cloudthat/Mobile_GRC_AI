/**
 * Connected mode: the same screens as demo mode, backed by the SecurityOS API.
 *
 * Flow:  config check → sign in → accept pending invite (if any) → /me
 *        → no org? onboarding creates one → app
 *
 * The context exposed to screens keeps the demo-mode shape (profile, statuses,
 * scoring, tenants, ...) plus `mode: 'api'`, `me`, `permissions`, and the
 * workflow helpers screens use in connected mode (findings, attestations, team).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AppShell } from '../SecurityOSApp';
import OnboardingView from '../views/securityos/OnboardingView';
import AnalysisView from '../views/securityos/AnalysisView';
import { calculateScore } from '../data/scoring';
import { getControlById, loadCatalog } from '../data/controls';
import { configProblems, AUTH_MODE } from '../lib/config';
import { initAuth, signIn, signOut } from '../lib/auth';
import { api, errorMessage, profileFromApi, profileToApi } from '../lib/api';
import { SignInScreen, CreateOrgConfirm, ConfigErrorScreen, LoadingScreen, Toasts } from './screens';

const ACTIVE_ORG_KEY = 'securityos_active_org';      // UI preference only
const PENDING_INVITE_KEY = 'securityos_pending_invite';

const EMPTY_PROFILE = {
  businessName: '', industry: '', employeeCount: '', emailProvider: '', cloudProviders: [], sensitiveData: [],
};

// Finding state → roadmap assignment status label
const STATE_TO_ASSIGNMENT = {
  open: 'ASSIGNED', assigned: 'ASSIGNED', reopened: 'ASSIGNED',
  in_progress: 'IN_PROGRESS', submitted_for_review: 'READY_FOR_VERIFICATION',
  risk_accepted: 'ACCEPTED_RISK',
};
const OPEN_STATES = new Set(['open', 'assigned', 'reopened', 'in_progress', 'submitted_for_review', 'risk_accepted']);

function captureInviteFromUrl() {
  const url = new URL(window.location.href);
  const token = url.searchParams.get('invite');
  if (!token) return;
  sessionStorage.setItem(PENDING_INVITE_KEY, token);
  url.searchParams.delete('invite');
  window.history.replaceState({}, '', url.toString());
}

export default function ApiSecurityOSApp() {
  const problems = configProblems();
  const [auth, setAuth] = useState({ status: 'loading', user: null });
  const [me, setMe] = useState(null);
  const [orgData, setOrgData] = useState({});          // orgId → { profile, statuses }
  const [active, setActive] = useState({ findings: [], attestations: [], assignees: [] });
  const [activeOrgId, setActiveOrgId] = useState(() => localStorage.getItem(ACTIVE_ORG_KEY));
  const [toasts, setToasts] = useState([]);
  const [newOrg, setNewOrg] = useState(null);          // onboarding state when the user has no org
  const catalog = useMemo(() => loadCatalog(), []);
  const profileSaveTimer = useRef(null);

  const toast = useCallback((text, tone = 'info') => {
    const id = Math.random().toString(36).slice(2);
    setToasts(t => [...t, { id, text, tone }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), tone === 'error' ? 6000 : 3500);
  }, []);
  const fail = useCallback(err => toast(errorMessage(err), 'error'), [toast]);

  // ── Sign-in + invite ───────────────────────────────────────────────────────
  useEffect(() => {
    if (problems.length) return;
    captureInviteFromUrl();
    initAuth()
      .then(user => setAuth({ status: user ? 'signedIn' : 'signedOut', user }))
      .catch(err => { fail(err); setAuth({ status: 'signedOut', user: null }); });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadMe = useCallback(async () => {
    const data = await api.me();
    setMe(data);
    return data;
  }, []);

  useEffect(() => {
    if (auth.status !== 'signedIn') return;
    (async () => {
      const invite = sessionStorage.getItem(PENDING_INVITE_KEY);
      if (invite) {
        sessionStorage.removeItem(PENDING_INVITE_KEY);
        try {
          const r = await api.acceptInvite(invite);
          localStorage.setItem(ACTIVE_ORG_KEY, r.org_id);
          setActiveOrgId(r.org_id);
          toast(`You joined as ${r.role.replace('_', ' ')}.`, 'success');
        } catch (err) { fail(err); }
      }
      try { await loadMe(); } catch (err) { fail(err); }
    })();
  }, [auth.status, loadMe, toast, fail]);

  const orgs = me?.organizations ?? [];
  const activeOrg = orgs.find(o => o.org_id === activeOrgId) ?? orgs[0] ?? null;
  const orgId = activeOrg?.org_id ?? null;
  const permissions = useMemo(() => new Set(activeOrg?.permissions ?? []), [activeOrg]);
  const can = useCallback(p => permissions.has(p), [permissions]);

  useEffect(() => {
    if (orgId && orgId !== activeOrgId) setActiveOrgId(orgId);
    if (orgId) localStorage.setItem(ACTIVE_ORG_KEY, orgId);
  }, [orgId, activeOrgId]);

  // ── Data loading ───────────────────────────────────────────────────────────
  const loadOrgSummary = useCallback(async id => {
    const [profile, statuses] = await Promise.all([api.getProfile(id), api.statuses(id)]);
    setOrgData(d => ({ ...d, [id]: { profile: profileFromApi(profile), statuses: statuses.statuses } }));
  }, []);

  const refreshActive = useCallback(async () => {
    if (!orgId) return;
    const org = orgs.find(o => o.org_id === orgId);
    const perms = new Set(org?.permissions ?? []);
    try {
      const [findings, attestations, assignees] = await Promise.all([
        api.findings(orgId),
        api.attestations(orgId),
        perms.has('finding.assign') ? api.assignees(orgId) : Promise.resolve({ assignees: [] }),
        loadOrgSummary(orgId),
      ]);
      setActive({ findings: findings.findings, attestations: attestations.attestations, assignees: assignees.assignees });
    } catch (err) { fail(err); }
  }, [orgId, orgs, loadOrgSummary, fail]);

  useEffect(() => { refreshActive(); }, [refreshActive]);

  useEffect(() => {
    // Other orgs: summaries for the Customers view
    orgs.filter(o => o.org_id !== orgId && !orgData[o.org_id]).forEach(o => loadOrgSummary(o.org_id).catch(() => {}));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgs, orgId]);

  // ── Derived state for screens ──────────────────────────────────────────────
  const profile = orgData[orgId]?.profile ?? EMPTY_PROFILE;
  const statuses = orgData[orgId]?.statuses ?? {};
  const scoring = calculateScore(statuses, profile, catalog);

  const findingsByControl = useMemo(() => {
    const map = {};
    for (const f of active.findings) for (const c of f.control_ids) (map[c] ??= []).push(f);
    return map;
  }, [active.findings]);

  const openFindingFor = useCallback(controlId => {
    const list = (findingsByControl[controlId] ?? []).filter(f => OPEN_STATES.has(f.state));
    return list.sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))[0] ?? null;
  }, [findingsByControl]);

  const assigneeNames = useMemo(
    () => Object.fromEntries(active.assignees.map(a => [a.user_id, a.display_name])),
    [active.assignees],
  );

  const assignments = useMemo(() => {
    const out = {};
    for (const controlId of Object.keys(findingsByControl)) {
      const f = openFindingFor(controlId);
      if (f?.assigned_to_user_id) {
        out[controlId] = {
          owner: assigneeNames[f.assigned_to_user_id] ?? f.assigned_to_user_id,
          userId: f.assigned_to_user_id,
          status: STATE_TO_ASSIGNMENT[f.state] ?? 'ASSIGNED',
          findingId: f.finding_id,
        };
      }
    }
    return out;
  }, [findingsByControl, openFindingFor, assigneeNames]);

  const attestations = useMemo(() => active.attestations.map(a => ({
    id: a.id,
    providerName: a.source_name,
    controlIds: a.control_ids,
    description: a.source_description,
    attesterName: a.created_by_name,
    attesterEmail: a.created_by_email,
    attestedAt: a.created_at,
    expiresAt: a.expires_at,
    status: a.status,
    validity: a.validity_days,
  })), [active.attestations]);

  // ── Actions ────────────────────────────────────────────────────────────────
  const run = useCallback(async (fn, success) => {
    try {
      const result = await fn();
      if (success) toast(success, 'success');
      await refreshActive();
      return result;
    } catch (err) { fail(err); throw err; }
  }, [refreshActive, toast, fail]);

  const updateStatus = useCallback((controlId, status, notes = null) => {
    if (!['fail', 'unknown', 'in_progress'].includes(status)) {
      toast('A control passes only when its fix is approved or an executive attests it.', 'error');
      return;
    }
    run(() => api.setStatus(orgId, controlId, status, notes)).catch(() => {});
  }, [orgId, run, toast]);

  const setProfile = useCallback(updater => {
    if (!orgId) return;
    if (!can('org.manage')) { toast('Only an admin can edit the business profile.', 'error'); return; }
    setOrgData(d => {
      const current = d[orgId]?.profile ?? EMPTY_PROFILE;
      const next = typeof updater === 'function' ? updater(current) : updater;
      clearTimeout(profileSaveTimer.current);
      profileSaveTimer.current = setTimeout(() => {
        api.saveProfile(orgId, profileToApi(next)).then(loadMe).catch(fail);
      }, 700);
      return { ...d, [orgId]: { ...(d[orgId] ?? {}), profile: next } };
    });
  }, [orgId, can, toast, fail, loadMe]);

  const ensureFinding = useCallback(async controlId => {
    const existing = openFindingFor(controlId);
    if (existing) return existing;
    const control = getControlById(controlId);
    const r = await api.createFinding(orgId, {
      title: control?.short_name ?? control?.name ?? controlId,
      description: control?.customer_impact || control?.description || 'Security gap',
      severity: control?.severity ?? 'medium',
      control_ids: [controlId],
    });
    return r.finding;
  }, [openFindingFor, orgId]);

  const workflow = {
    openFindings: active.findings.filter(f => OPEN_STATES.has(f.state)),
    findingsFor: controlId => findingsByControl[controlId] ?? [],
    openFindingFor,
    reportIssue: controlId => run(() => ensureFinding(controlId), 'Issue logged.'),
    startFix: controlId => run(async () => {
      const f = await ensureFinding(controlId);
      if (['open', 'assigned', 'reopened'].includes(f.state)) await api.transition(orgId, f.finding_id, { action: 'start' });
    }, "You're on it."),
    act: (findingId, action, extra = {}, success) =>
      run(() => api.transition(orgId, findingId, { action, ...extra }), success),
    assign: (controlId, userId) => run(async () => {
      const f = await ensureFinding(controlId);
      await api.transition(orgId, f.finding_id, { action: 'assign', assigned_to_user_id: userId });
    }, 'Assigned.'),
    createAttestation: body => run(() => api.createAttestation(orgId, body)),
    assignees: active.assignees,
  };

  const team = {
    members: () => api.members(orgId),
    invites: () => api.invites(orgId),
    createInvite: body => api.createInvite(orgId, body),
    revokeInvite: id => api.revokeInvite(orgId, id),
    removeMember: userId => api.removeMember(orgId, userId),
    auditVerify: () => api.auditVerify(orgId),
  };

  const tenants = orgs.map(o => ({
    id: o.org_id,
    name: o.org_name,
    profile: orgData[o.org_id]?.profile ?? { ...EMPTY_PROFILE, businessName: o.org_name },
    statuses: orgData[o.org_id]?.statuses ?? {},
  }));

  const switchTenant = useCallback(id => { setActiveOrgId(id); localStorage.setItem(ACTIVE_ORG_KEY, id); }, []);

  const addTenant = useCallback(async (name = 'New Client') => {
    try {
      const r = me?.msp_id ? await api.createMspOrg(me.msp_id, { name }) : await api.createOrg({ name });
      await loadMe();
      switchTenant(r.org_id);
      toast(`${name} created.`, 'success');
    } catch (err) { fail(err); }
  }, [me, loadMe, switchTenant, toast, fail]);

  const removeTenant = useCallback(async id => {
    const org = orgs.find(o => o.org_id === id);
    if (!org?.msp_id || !org.permissions.includes('org.manage')) {
      toast('Only an admin of an MSP-managed client org can remove it.', 'error');
      return;
    }
    if (!window.confirm(`Remove ${org.org_name}? Its history is kept for audit, but nobody can access it.`)) return;
    try { await api.deleteMspOrg(org.msp_id, id); await loadMe(); } catch (err) { fail(err); }
  }, [orgs, loadMe, toast, fail]);

  const renameTenant = useCallback(async (id, name) => {
    const current = orgData[id]?.profile ?? EMPTY_PROFILE;
    try { await api.saveProfile(id, profileToApi({ ...current, businessName: name })); await loadMe(); await loadOrgSummary(id); }
    catch (err) { fail(err); }
  }, [orgData, loadMe, loadOrgSummary, fail]);

  // ── Render gates ───────────────────────────────────────────────────────────
  if (problems.length) return <ConfigErrorScreen problems={problems} />;
  if (auth.status === 'loading') return <LoadingScreen text="Signing you in…" />;
  if (auth.status === 'signedOut') {
    return <SignInScreen devMode={AUTH_MODE === 'dev'} onSignIn={u => signIn(u).then(() => initAuth()).then(user => user && setAuth({ status: 'signedIn', user })).catch(fail)} toasts={<Toasts items={toasts} />} />;
  }
  if (!me) return <LoadingScreen text="Loading your organizations…" toasts={<Toasts items={toasts} />} />;

  if (!orgs.length || newOrg) {
    const state = newOrg ?? { step: 'onboarding', profile: { ...EMPTY_PROFILE } };
    const setNewProfile = updater => setNewOrg(s => {
      const base = s ?? state;
      const p = typeof updater === 'function' ? updater(base.profile) : updater;
      return { ...base, profile: p };
    });
    if (state.step === 'onboarding') {
      return <OnboardingView profile={state.profile} setProfile={setNewProfile} skipLabel="Skip — I'll fill this in later" onComplete={() => setNewOrg(s => ({ ...(s ?? state), step: 'confirm' }))} />;
    }
    if (state.step === 'confirm') {
      return (
        <CreateOrgConfirm
          profile={state.profile}
          me={me}
          onBack={() => setNewOrg(s => ({ ...s, step: 'onboarding' }))}
          onCreate={async ({ alsoExecutive }) => {
            try {
              const p = profileToApi(state.profile);
              const r = await api.createOrg({
                name: p.business_name, industry: p.industry, employee_count: p.employee_count,
                email_provider: p.email_provider, cloud_providers: p.cloud_providers,
                sensitive_data: p.sensitive_data, also_executive: alsoExecutive,
              });
              switchTenant(r.org_id);
              await loadMe();
              setNewOrg(s => ({ ...s, step: 'analysis' }));
            } catch (err) { fail(err); }
          }}
          toasts={<Toasts items={toasts} />}
        />
      );
    }
    return <AnalysisView profile={state.profile} onComplete={() => setNewOrg(null)} />;
  }

  const data = {
    mode: 'api',
    me,
    activeOrg,
    permissions,
    can,
    roles: activeOrg?.roles ?? [],
    profile, setProfile, statuses, updateStatus, scoring, catalog,
    attestations, addAttestation: () => {},
    assignments,
    setAssignment: (controlId, value) => (value?.userId ? workflow.assign(controlId, value.userId) : Promise.resolve()),
    tenants, activeTenantId: orgId, switchTenant, addTenant, removeTenant, renameTenant,
    workflow,
    team,
    refresh: refreshActive,
    toast,
    signOut,
    startNewOrg: () => setNewOrg({ step: 'onboarding', profile: { ...EMPTY_PROFILE } }),
  };

  return <AppShell data={data} banner={<Toasts items={toasts} />} />;
}
