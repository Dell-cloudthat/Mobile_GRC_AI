/**
 * One AI app: why the team is probably using it, why it's risky, what to do,
 * safer options, who uses it, evidence, and the business decision.
 */
import { useEffect, useState } from 'react';
import { useApp } from '../../../SecurityOSApp';
import { errorMessage } from '../../../lib/errors';
import { LEVEL, RiskBadge, Section, StatusChip, SOURCE_LABEL, timeAgo } from './aiUi';
import {
  ArrowLeft, Lightbulb, AlertTriangle, ArrowRightCircle, ShieldCheck, Users, FileSearch, MessagesSquare,
  CheckCircle2, Ban, Clock, Eye, BadgeCheck, ExternalLink,
} from 'lucide-react';

function daysFromNow(n) {
  return new Date(Date.now() + n * 86400000).toISOString().slice(0, 10);
}

export default function AIAppDetailView({ appKey, onBack }) {
  const { ai, reloadAi, roles = [], mode } = useApp();
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [showAllUsers, setShowAllUsers] = useState(false);

  useEffect(() => {
    let live = true;
    setD(null); setError(null);
    ai.detail(appKey).then(x => live && setD(x)).catch(e => live && setError(errorMessage(e)));
    return () => { live = false; };
  // The adapter object is rebuilt on every render in connected mode; its key (the org) is what matters.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ai?.key, appKey]);

  const showMsp = mode === 'demo' || roles.includes('msp_technician');

  if (error) return <Frame onBack={onBack}><p className="p-5 text-sm text-red-300">{error}</p></Frame>;
  if (!d) return <Frame onBack={onBack}><p className="p-5 text-sm text-slate-500">Loading…</p></Frame>;

  const l = LEVEL[d.risk.level];
  const users = d.users ?? [];
  const visibleUsers = showAllUsers ? users : users.slice(0, 5);

  return (
    <Frame onBack={onBack}>
      {/* Header */}
      <div className={`px-5 pt-4 pb-5 border-b border-slate-800 ${l.bg}`}>
        <p className="text-[11px] text-slate-400">{d.category_label}{d.vendor ? ` · ${d.vendor}` : ''}</p>
        <h1 className="text-2xl font-bold text-white mt-0.5">{d.name}</h1>
        <div className="flex flex-wrap items-center gap-2 mt-3">
          <RiskBadge risk={d.risk} size="lg" />
          <StatusChip status={d.status} label={d.status_label} />
          {d.admin_consented && <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">Admin-approved for whole org in Microsoft 365</span>}
        </div>
        <p className="text-xs text-slate-300 mt-3">
          {d.user_count} {d.user_count === 1 ? 'person' : 'people'} · last activity {timeAgo(d.last_seen)} · seen via {d.sources.map(s => SOURCE_LABEL[s] ?? s).join(', ')}
        </p>
        {d.still_in_use && (
          <p className="mt-3 text-xs text-amber-100 bg-amber-500/15 border border-amber-500/30 rounded-lg p-2.5 flex gap-2">
            <AlertTriangle size={14} className="shrink-0 mt-0.5" /> Blocked, but it showed up again after the block. Check that consent was revoked.
          </p>
        )}
      </div>

      {/* Recommended next step */}
      <Section title="Recommended next step">
        <div className="flex gap-3 p-3 rounded-xl bg-indigo-500/10 border border-indigo-500/30">
          <ArrowRightCircle size={18} className="text-indigo-300 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-white">{d.recommended_action.label}</p>
            <p className="text-xs text-slate-300 mt-0.5">{d.recommended_action.detail}</p>
          </div>
        </div>
      </Section>

      {/* Why they use it */}
      <Section title="Why your team probably uses it">
        <p className="text-sm text-white flex gap-2"><Lightbulb size={16} className="text-yellow-300 shrink-0 mt-0.5" />{d.likely_use.headline}</p>
        {d.likely_use.by_department.length > 0 && (
          <ul className="mt-3 space-y-2">
            {d.likely_use.by_department.map(b => (
              <li key={b.department} className="text-xs text-slate-300 flex gap-2">
                <span className="shrink-0 w-24 text-slate-400">{b.department} ({b.users})</span>
                <span>{b.reason}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-slate-400 mt-3">The need behind it: <span className="text-slate-200">{d.likely_use.underlying_need}</span></p>
        <p className="text-[10px] text-slate-600 mt-1">{d.likely_use.basis}</p>
      </Section>

      {/* What it is */}
      {d.app && (
        <Section title="What it is" right={d.app.website && (
          <a href={d.app.website} target="_blank" rel="noreferrer" className="text-[11px] text-indigo-300 flex items-center gap-1">Website <ExternalLink size={11} /></a>
        )}>
          <p className="text-sm text-slate-200">{d.app.summary}</p>
          {d.app.common_uses?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {d.app.common_uses.map(u => <span key={u} className="text-[11px] px-2 py-1 rounded-lg bg-slate-900 border border-slate-800 text-slate-300">{u}</span>)}
            </div>
          )}
          <PlanFacts app={d.app} planAssumed={d.risk.plan_assumed} />
          {d.app.notes && <p className="text-xs text-slate-400 mt-2">{d.app.notes}</p>}
        </Section>
      )}

      {/* Why it's risky */}
      <Section title="Why it's risky">
        <ul className="space-y-2.5">
          {d.risk_factors.map(f => (
            <li key={f.key + f.label} className="flex gap-3">
              <span className={`shrink-0 w-9 text-right text-xs font-semibold tabular-nums ${l.text}`}>+{f.points}</span>
              <span>
                <span className="block text-sm text-slate-100">{f.label}</span>
                {f.detail && <span className="block text-[11px] text-slate-500 mt-0.5">{f.detail}</span>}
              </span>
            </li>
          ))}
        </ul>
        {d.risk.plan_assumed === 'consumer' && d.app?.tiers?.business && (
          <p className="text-[11px] text-slate-500 mt-3">
            Scored as the {d.risk.plan_label} plan because we can't see billing.
            {d.risk_if_business && <> On {d.app.tiers.business.label} it would score <span className={LEVEL[d.risk_if_business.level].text}>{d.risk_if_business.score} ({d.risk_if_business.level})</span>.</>}
          </p>
        )}
      </Section>

      {/* Safer options */}
      {d.alternatives?.length > 0 && (
        <Section title="Safer options">
          <ul className="space-y-2">
            {d.alternatives.map(a => (
              <li key={a.app_id + a.name} className="p-3 rounded-xl bg-slate-900 border border-slate-800">
                <p className="text-sm text-white font-medium flex items-center gap-2">
                  {a.name}
                  {a.already_licensed && <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/15 text-green-300 border border-green-500/30">Likely already licensed</span>}
                </p>
                <p className="text-xs text-slate-400 mt-1">{a.why}</p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* MSP talking point */}
      {showMsp && d.msp_opportunity && (
        <Section title="For your MSP conversation">
          <p className="text-sm text-slate-200 flex gap-2"><MessagesSquare size={16} className="text-indigo-300 shrink-0 mt-0.5" />{d.msp_opportunity}</p>
        </Section>
      )}

      {/* Decision */}
      <DecisionPanel d={d} onDecided={async next => { setD(next); await reloadAi(); }} />

      {/* People */}
      {users.length > 0 && (
        <Section title={`Who's using it (${users.length})`}>
          <ul className="divide-y divide-slate-800/70">
            {visibleUsers.map(u => (
              <li key={u.user} className="py-2 flex items-center justify-between gap-3 text-sm">
                <span className="text-slate-200 truncate flex items-center gap-2"><Users size={13} className="text-slate-500" />{u.user}</span>
                <span className="text-[11px] text-slate-500 shrink-0">{u.department ?? '—'}</span>
              </li>
            ))}
          </ul>
          {users.length > 5 && (
            <button onClick={() => setShowAllUsers(v => !v)} className="mt-2 text-xs text-indigo-300">
              {showAllUsers ? 'Show fewer' : `Show all ${users.length}`}
            </button>
          )}
        </Section>
      )}

      {/* Evidence */}
      <Section title="Evidence">
        <dl className="text-xs space-y-1.5">
          {d.evidence.raw_names.length > 0 && <Row k="Seen as" v={d.evidence.raw_names.join(', ')} />}
          {d.evidence.domains.length > 0 && <Row k="Domains" v={d.evidence.domains.join(', ')} />}
          {d.evidence.scopes.length > 0 && <Row k="Permissions" v={d.evidence.scopes.join(' ')} mono />}
          <Row k="First seen" v={d.first_seen ? new Date(d.first_seen).toLocaleDateString() : '—'} />
        </dl>
        <p className="text-[10px] text-slate-600 mt-3 flex gap-1.5"><FileSearch size={11} className="shrink-0 mt-0.5" />Vendor facts reviewed {d.catalog_reviewed_at}. {d.disclaimer}</p>
      </Section>

      {/* History */}
      {d.decision_history?.length > 0 && (
        <Section title="Decision history">
          <ul className="space-y-2">
            {d.decision_history.map((h, i) => (
              <li key={i} className="text-xs text-slate-300">
                <span className="text-white">{h.label}</span> · {h.decided_by_name} · {new Date(h.decided_at).toLocaleDateString()}
                {h.expires_at && <> · until {new Date(h.expires_at).toLocaleDateString()}</>}
                {h.note && <span className="block text-slate-500 mt-0.5">“{h.note}”</span>}
              </li>
            ))}
          </ul>
        </Section>
      )}
      <div className="h-8" />
    </Frame>
  );
}

function Frame({ onBack, children }) {
  return (
    <div className="flex flex-col min-h-full">
      <div className="sticky top-0 z-10 bg-slate-950/95 backdrop-blur px-3 pt-10 pb-2 border-b border-slate-800">
        <button onClick={onBack} className="flex items-center gap-1.5 text-sm text-slate-300 px-2 py-1.5 rounded-lg hover:bg-slate-900">
          <ArrowLeft size={16} /> AI Usage
        </button>
      </div>
      {children}
    </div>
  );
}

function Row({ k, v, mono = false }) {
  return (
    <div className="flex gap-3">
      <dt className="w-20 shrink-0 text-slate-500">{k}</dt>
      <dd className={`text-slate-300 break-words min-w-0 ${mono ? 'font-mono text-[11px]' : ''}`}>{v}</dd>
    </div>
  );
}

const TRAINS = {
  yes: { t: 'Trains on your data', c: 'text-red-300' },
  opt_out: { t: 'Trains unless each user opts out', c: 'text-orange-300' },
  no: { t: "Doesn't train on your data", c: 'text-green-300' },
  unknown: { t: 'Not confirmed', c: 'text-slate-400' },
};

function PlanFacts({ app, planAssumed }) {
  const rows = [['consumer', app.tiers.consumer], ['business', app.tiers.business]].filter(([, t]) => t);
  return (
    <div className="mt-3 rounded-xl border border-slate-800 overflow-hidden">
      {rows.map(([key, t]) => (
        <div key={key} className={`px-3 py-2.5 text-xs flex items-start justify-between gap-3 ${key === planAssumed ? 'bg-slate-900' : ''} ${key === 'business' ? 'border-t border-slate-800' : ''}`}>
          <span className="text-slate-300">
            {t.label}
            {key === planAssumed && <span className="ml-1.5 text-[10px] text-indigo-300">(scored)</span>}
          </span>
          <span className="text-right">
            <span className={`block ${TRAINS[t.trains_on_inputs]?.c}`}>{TRAINS[t.trains_on_inputs]?.t}</span>
            <span className="block text-slate-500">{t.admin_controls ? 'Admin controls' : 'No admin controls'}</span>
          </span>
        </div>
      ))}
      {!app.tiers.business && <div className="px-3 py-2 text-[11px] text-slate-500 border-t border-slate-800">No business plan available.</div>}
      <div className="px-3 py-2 text-[11px] text-slate-500 border-t border-slate-800">
        SOC 2: {app.soc2 === true ? 'yes' : app.soc2 === false ? 'no' : 'not confirmed'}
        {app.hq_country && <> · HQ: {app.hq_country}</>}
      </div>
    </div>
  );
}

// ── Decision panel ────────────────────────────────────────────────────────────

const OPTIONS = [
  { id: 'approved_business', label: 'Approve business plan', icon: BadgeCheck, tone: 'bg-green-600 hover:bg-green-500 text-white' },
  { id: 'approved', label: 'Approve as used', icon: CheckCircle2, tone: 'bg-slate-800 border border-green-500/30 text-green-200' },
  { id: 'blocked', label: 'Block', icon: Ban, tone: 'bg-slate-800 border border-red-500/30 text-red-200' },
  { id: 'risk_accepted', label: 'Accept risk for now…', icon: Clock, tone: 'bg-slate-800 border border-amber-500/30 text-amber-200' },
  { id: 'under_review', label: 'Mark under review', icon: Eye, tone: 'bg-slate-800 border border-slate-700 text-slate-200' },
];

function DecisionPanel({ d, onDecided }) {
  const { ai, toast } = useApp();
  const [choice, setChoice] = useState(null);
  const [note, setNote] = useState('');
  const [until, setUntil] = useState(daysFromNow(30));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  if (!d.can_decide) {
    return (
      <Section title="Decision">
        <p className="text-xs text-slate-400 flex gap-2"><ShieldCheck size={14} className="shrink-0" />
          Approving or blocking an AI tool is the business's call, so an executive makes it. {d.decision ? `Current: ${d.decision.label}.` : ''}
        </p>
      </Section>
    );
  }

  const highRisk = ['critical', 'high'].includes(d.risk.level);
  const maxDays = d.risk.level === 'critical' ? 90 : 365;
  const options = OPTIONS.filter(o => o.id !== 'approved_business' || d.app?.tiers?.business)
    .filter(o => o.id !== d.status);
  const needsNote = choice === 'risk_accepted' || (choice === 'approved' && highRisk);
  const noteOk = !needsNote || note.trim().length >= 20;

  async function submit() {
    setBusy(true); setErr(null);
    try {
      const body = { decision: choice, note: note.trim() || null };
      if (choice === 'risk_accepted') body.expires_at = new Date(`${until}T23:59:59Z`).toISOString();
      const next = await ai.decide(d.app_key, body);
      setChoice(null); setNote('');
      await onDecided(next);
      toast?.(`${next.status_label}.`, 'success');
    } catch (e) {
      setErr(errorMessage(e));
    } finally { setBusy(false); }
  }

  return (
    <Section title="Decision">
      {d.decision && (
        <p className="text-xs text-slate-400 mb-3">Current: <span className="text-white">{d.decision.label}</span> by {d.decision.decided_by_name}{d.decision.note ? ` — “${d.decision.note}”` : ''}</p>
      )}
      {!choice ? (
        <div className="grid grid-cols-1 gap-2">
          {options.map(o => (
            <button key={o.id} onClick={() => setChoice(o.id)}
                    className={`w-full py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 ${o.tone}`}>
              <o.icon size={15} /> {o.label}
            </button>
          ))}
        </div>
      ) : (
        <div className="space-y-2 p-3 rounded-xl bg-slate-900 border border-slate-800">
          <p className="text-sm text-white font-medium">{OPTIONS.find(o => o.id === choice).label}</p>
          {choice === 'approved_business' && <p className="text-xs text-slate-400">Moves the score to the {d.app.tiers.business.label} plan. Make sure people actually move to it.</p>}
          {choice === 'blocked' && <p className="text-xs text-slate-400">Then revoke the app's consent and tell the {d.user_count} {d.user_count === 1 ? 'person' : 'people'} using it what to use instead.</p>}
          {choice === 'risk_accepted' && (
            <label className="block text-xs text-slate-400">Until (max {maxDays} days)
              <input type="date" value={until} min={daysFromNow(1)} max={daysFromNow(maxDays)} onChange={e => setUntil(e.target.value)}
                     className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white" />
            </label>
          )}
          <label className="block text-xs text-slate-400">
            {needsNote ? 'Why is this acceptable? (20+ characters)' : 'Note (optional)'}
            <textarea value={note} onChange={e => setNote(e.target.value)} rows={3}
                      className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white" />
          </label>
          {err && <p className="text-xs text-red-300">{err}</p>}
          <div className="flex gap-2">
            <button onClick={() => { setChoice(null); setErr(null); }} className="flex-1 py-2.5 rounded-lg bg-slate-800 text-slate-300 text-sm">Cancel</button>
            <button onClick={submit} disabled={busy || !noteOk}
                    className="flex-1 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-semibold">
              {busy ? 'Saving…' : 'Confirm'}
            </button>
          </div>
        </div>
      )}
    </Section>
  );
}
