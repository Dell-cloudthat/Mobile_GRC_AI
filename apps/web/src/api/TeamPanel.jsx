/**
 * Connected-mode Settings sections: your account, team & invites, audit check.
 */
import { useCallback, useEffect, useState } from 'react';
import { useApp } from '../SecurityOSApp';
import { errorMessage } from '../lib/errors';
import { LogOut, UserPlus, Copy, Check, Trash2, ShieldCheck, ShieldAlert, Building2 } from 'lucide-react';

const ROLE_LABEL = {
  admin: 'Admin', executive: 'Executive', engineer: 'Engineer',
  msp_technician: 'MSP Technician', auditor: 'Auditor',
};
const ROLE_HELP = {
  engineer: 'Fixes issues and submits them for review.',
  executive: 'Approves high-risk fixes and attests controls. Must be someone at the business (not MSP staff).',
  auditor: 'Read-only, time-limited access plus audit export.',
  msp_technician: 'MSP staff: assigns and fixes issues. Cannot attest.',
  admin: 'Manages the team and settings. Cannot attest or approve fixes.',
};

function Section({ title, children }) {
  return (
    <div className="mt-6">
      <p className="px-5 text-xs text-slate-500 uppercase tracking-wider mb-2">{title}</p>
      <div className="bg-slate-900 border-y border-slate-800">{children}</div>
    </div>
  );
}

function RoleChip({ role }) {
  return <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-600/20 text-indigo-300">{ROLE_LABEL[role] ?? role}</span>;
}

export function AccountSection() {
  const { me, roles, activeOrg, signOut, startNewOrg } = useApp();
  return (
    <Section title="Your account">
      <div className="px-5 py-4 border-b border-slate-800">
        <p className="text-sm text-white font-medium">{me.display_name}</p>
        <p className="text-xs text-slate-400">{me.email}</p>
        <div className="flex flex-wrap gap-1.5 mt-2">
          {roles.map(r => <RoleChip key={r} role={r} />)}
          <span className="text-[10px] text-slate-500 self-center">in {activeOrg?.org_name}</span>
        </div>
      </div>
      <button onClick={startNewOrg} className="w-full flex items-center gap-3 px-5 py-4 border-b border-slate-800 text-sm text-slate-300 hover:bg-slate-800/50">
        <Building2 size={15} /> Create another organization
      </button>
      <button onClick={signOut} className="w-full flex items-center gap-3 px-5 py-4 text-sm text-red-400 hover:bg-slate-800/50">
        <LogOut size={15} /> Sign out
      </button>
    </Section>
  );
}

export function TeamSection() {
  const { team, can, me, toast } = useApp();
  const [members, setMembers] = useState([]);
  const [invites, setInvites] = useState([]);
  const [role, setRole] = useState('engineer');
  const [auditorUntil, setAuditorUntil] = useState('');
  const [created, setCreated] = useState(null);   // { link, role }
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [m, i] = await Promise.all([team.members(), team.invites()]);
      setMembers(m.members);
      setInvites(i.invites.filter(x => x.status === 'pending'));
    } catch (err) { toast(errorMessage(err), 'error'); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { if (can('org.manage')) load(); }, [can, load]);

  if (!can('org.manage')) return null;

  // Group membership rows by person
  const people = Object.values(members.reduce((acc, m) => {
    const p = acc[m.user_id] ??= { user_id: m.user_id, user: m.user, roles: [], expires: m.expires_at };
    p.roles.push(m.role);
    return acc;
  }, {}));

  async function createInvite() {
    setBusy(true);
    try {
      const body = { role };
      if (role === 'auditor') body.membership_expires_at = new Date(`${auditorUntil}T23:59:59Z`).toISOString();
      const r = await team.createInvite(body);
      setCreated({ link: `${window.location.origin}/?invite=${encodeURIComponent(r.token)}`, role });
      setCopied(false);
      await load();
    } catch (err) { toast(errorMessage(err), 'error'); } finally { setBusy(false); }
  }

  return (
    <Section title="Team">
      {people.map(p => (
        <div key={p.user_id} className="flex items-center justify-between gap-3 px-5 py-3 border-b border-slate-800">
          <div className="min-w-0">
            <p className="text-sm text-white truncate">{p.user?.display_name ?? p.user_id}{p.user_id === me.user_id ? ' (you)' : ''}</p>
            <div className="flex flex-wrap gap-1 mt-1">{p.roles.map(r => <RoleChip key={r} role={r} />)}</div>
            {p.expires && <p className="text-[10px] text-slate-500 mt-1">Access ends {new Date(p.expires).toLocaleDateString()}</p>}
          </div>
          {p.user_id !== me.user_id && (
            <button title="Remove" className="text-slate-500 hover:text-red-400"
                    onClick={async () => {
                      if (!window.confirm(`Remove ${p.user?.display_name ?? p.user_id} from this organization?`)) return;
                      try { await team.removeMember(p.user_id); await load(); } catch (err) { toast(errorMessage(err), 'error'); }
                    }}>
              <Trash2 size={15} />
            </button>
          )}
        </div>
      ))}

      <div className="px-5 py-4 space-y-2 border-b border-slate-800">
        <p className="text-xs text-slate-400 flex items-center gap-1.5"><UserPlus size={13} /> Invite someone</p>
        <select value={role} onChange={e => setRole(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
          {['engineer', 'executive', 'auditor', 'msp_technician', 'admin'].map(r => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
        </select>
        <p className="text-[11px] text-slate-500">{ROLE_HELP[role]}</p>
        {role === 'auditor' && (
          <label className="block text-xs text-slate-400">Access ends
            <input type="date" value={auditorUntil} onChange={e => setAuditorUntil(e.target.value)}
                   min={new Date(Date.now() + 86400000).toISOString().slice(0, 10)}
                   className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white" />
          </label>
        )}
        <button onClick={createInvite} disabled={busy || (role === 'auditor' && !auditorUntil)}
                className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-semibold">
          {busy ? 'Creating…' : 'Create invite link'}
        </button>
        {created && (
          <div className="p-3 rounded-xl bg-indigo-500/10 border border-indigo-500/30 space-y-2">
            <p className="text-xs text-indigo-200">Send this {ROLE_LABEL[created.role]} invite link. It works once and expires in 7 days; it won't be shown again.</p>
            <div className="flex gap-2">
              <input readOnly value={created.link} className="flex-1 min-w-0 bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5 text-[11px] text-slate-300" />
              <button onClick={async () => { await navigator.clipboard.writeText(created.link); setCopied(true); }}
                      className="px-3 rounded-lg bg-slate-800 border border-slate-700 text-slate-200">
                {copied ? <Check size={14} /> : <Copy size={14} />}
              </button>
            </div>
          </div>
        )}
      </div>

      {invites.map(i => (
        <div key={i.invite_id} className="flex items-center justify-between px-5 py-3 border-b border-slate-800 last:border-0">
          <div>
            <p className="text-xs text-slate-300">Pending {ROLE_LABEL[i.role]} invite</p>
            <p className="text-[10px] text-slate-500">Expires {new Date(i.expires_at).toLocaleDateString()}</p>
          </div>
          <button className="text-xs text-red-400" onClick={async () => {
            try { await team.revokeInvite(i.invite_id); await load(); } catch (err) { toast(errorMessage(err), 'error'); }
          }}>Revoke</button>
        </div>
      ))}
    </Section>
  );
}

export function AuditSection() {
  const { team, can, toast } = useApp();
  const [result, setResult] = useState(null);
  if (!can('audit.export')) return null;
  return (
    <Section title="Audit trail">
      <div className="px-5 py-4 space-y-2">
        <p className="text-xs text-slate-400">Every grant, invite, status change, and attestation is recorded in a tamper-evident chain.</p>
        <button onClick={async () => { try { setResult(await team.auditVerify()); } catch (err) { toast(errorMessage(err), 'error'); } }}
                className="w-full py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-slate-200 text-sm font-medium">
          Verify audit trail integrity
        </button>
        {result && (
          <p className={`text-xs flex items-center gap-1.5 ${result.valid ? 'text-green-400' : 'text-red-400'}`}>
            {result.valid ? <ShieldCheck size={14} /> : <ShieldAlert size={14} />}
            {result.valid ? `Intact — ${result.checked} events verified.` : `Tampering detected at event #${result.first_break_seq}.`}
          </p>
        )}
      </div>
    </Section>
  );
}
