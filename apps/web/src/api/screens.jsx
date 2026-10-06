/**
 * Small full-screen states used in connected mode.
 */
import { useState } from 'react';
import { Shield, Loader2, AlertTriangle, CheckCircle2, Info } from 'lucide-react';

function Frame({ children, toasts = null }) {
  return (
    <div className="min-h-screen bg-slate-950 text-white flex items-center justify-center px-6">
      {toasts}
      <div className="w-full max-w-sm">{children}</div>
    </div>
  );
}

function Brand({ subtitle }) {
  return (
    <div className="text-center mb-8">
      <div className="w-14 h-14 rounded-2xl bg-indigo-600 flex items-center justify-center mx-auto mb-4">
        <Shield size={28} />
      </div>
      <h1 className="text-2xl font-bold">SecurityOS</h1>
      {subtitle && <p className="text-slate-400 text-sm mt-1">{subtitle}</p>}
    </div>
  );
}

export function Toasts({ items }) {
  if (!items?.length) return null;
  const styles = {
    error: 'bg-red-500/15 border-red-500/40 text-red-200',
    success: 'bg-green-500/15 border-green-500/40 text-green-200',
    info: 'bg-slate-800 border-slate-700 text-slate-200',
  };
  const icons = { error: AlertTriangle, success: CheckCircle2, info: Info };
  return (
    <div className="fixed top-3 inset-x-0 z-50 flex flex-col items-center gap-2 px-4 pointer-events-none" role="status" aria-live="polite">
      {items.map(t => {
        const Icon = icons[t.tone] ?? Info;
        return (
          <div key={t.id} className={`max-w-md w-full flex items-start gap-2 px-3 py-2.5 rounded-xl border text-sm shadow-lg backdrop-blur ${styles[t.tone] ?? styles.info}`}>
            <Icon size={16} className="shrink-0 mt-0.5" />
            <span>{t.text}</span>
          </div>
        );
      })}
    </div>
  );
}

export function LoadingScreen({ text, toasts = null }) {
  return (
    <Frame toasts={toasts}>
      <div className="flex flex-col items-center gap-3 text-slate-400">
        <Loader2 className="animate-spin" size={28} />
        <p className="text-sm">{text}</p>
      </div>
    </Frame>
  );
}

export function ConfigErrorScreen({ problems }) {
  return (
    <Frame>
      <Brand subtitle="This deployment isn't fully configured." />
      <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-sm text-red-200 space-y-1">
        {problems.map(p => <p key={p}>• {p}</p>)}
      </div>
      <p className="text-xs text-slate-500 mt-4 text-center">See docs/deploy-azure.md, step 5.</p>
    </Frame>
  );
}

export function SignInScreen({ devMode, onSignIn, toasts = null }) {
  const [busy, setBusy] = useState(false);
  const [userId, setUserId] = useState('');
  const [name, setName] = useState('');
  const [mspId, setMspId] = useState('');
  const pendingInvite = typeof window !== 'undefined' && sessionStorage.getItem('securityos_pending_invite');

  async function go(payload) {
    setBusy(true);
    try { await onSignIn(payload); } finally { setBusy(false); }
  }

  return (
    <Frame toasts={toasts}>
      <Brand subtitle="Assess, fix, and sign off on security — from your phone." />
      {pendingInvite && (
        <div className="mb-4 bg-indigo-500/10 border border-indigo-500/30 rounded-xl p-3 text-sm text-indigo-200 text-center">
          You've been invited to a team. Sign in to accept.
        </div>
      )}

      {devMode ? (
        <form
          className="space-y-3"
          onSubmit={e => { e.preventDefault(); if (userId.trim()) go({ user_id: userId.trim(), name: name.trim() || undefined, msp_id: mspId.trim() || undefined }); }}
        >
          <p className="text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-2">
            Local dev sign-in. Not available in production.
          </p>
          <input className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-3 text-sm placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                 placeholder="User ID (e.g. ace)" value={userId} onChange={e => setUserId(e.target.value)} autoFocus />
          <input className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-3 text-sm placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                 placeholder="Display name (optional)" value={name} onChange={e => setName(e.target.value)} />
          <input className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-3 text-sm placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                 placeholder="MSP ID (optional — sign in as MSP staff)" value={mspId} onChange={e => setMspId(e.target.value)} />
          <button disabled={busy || !userId.trim()} className="w-full py-3.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm font-semibold">
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      ) : (
        <button onClick={() => go()} disabled={busy}
                className="w-full py-3.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm font-semibold">
          {busy ? 'Redirecting…' : 'Sign in or create account'}
        </button>
      )}
    </Frame>
  );
}

export function CreateOrgConfirm({ profile, me, onBack, onCreate, toasts = null }) {
  const [alsoExecutive, setAlsoExecutive] = useState(!me?.msp_id);
  const [busy, setBusy] = useState(false);
  return (
    <Frame toasts={toasts}>
      <Brand subtitle="Create your organization" />
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-1 mb-4">
        <p className="text-white font-semibold">{profile.businessName || 'My Business'}</p>
        <p className="text-xs text-slate-400">{[profile.industry, profile.employeeCount && `${profile.employeeCount} employees`].filter(Boolean).join(' · ')}</p>
      </div>
      <p className="text-sm text-slate-300 mb-3">You'll be the <span className="font-semibold text-white">admin</span>: you manage the team and settings.</p>
      <label className="flex items-start gap-3 bg-slate-900 border border-slate-800 rounded-xl p-3 mb-5 cursor-pointer">
        <input type="checkbox" className="mt-1 accent-indigo-500" checked={alsoExecutive} onChange={e => setAlsoExecutive(e.target.checked)} />
        <span className="text-sm">
          <span className="text-white font-medium">I also sign off on security for this business</span>
          <span className="block text-xs text-slate-400 mt-0.5">
            Adds the executive role: approve fixes and attest controls. Typical when the owner runs IT.
            You can never approve a fix you did yourself.
          </span>
        </span>
      </label>
      <button disabled={busy} onClick={async () => { setBusy(true); try { await onCreate({ alsoExecutive }); } finally { setBusy(false); } }}
              className="w-full py-3.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm font-semibold">
        {busy ? 'Creating…' : 'Create organization'}
      </button>
      <button onClick={onBack} className="w-full py-3 text-slate-500 text-sm mt-2">Back</button>
    </Frame>
  );
}
