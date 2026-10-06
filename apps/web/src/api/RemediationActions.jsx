/**
 * Connected-mode actions for one control: the fix → review → approve workflow.
 *
 * What a person sees depends on their permissions and on separation of duties:
 * whoever did the work on a High/Critical fix can't approve it, and nobody can
 * mark a control "passing" by hand. The server enforces all of this; the UI
 * just avoids offering buttons that would be refused.
 */
import { useState } from 'react';
import { useApp } from '../SecurityOSApp';
import { CheckCheck, ShieldCheck, Play, Send, Undo2, Flag, Hourglass, ShieldOff, RotateCcw } from 'lucide-react';

const HIGH = new Set(['critical', 'high']);

function daysFromNow(n) {
  const d = new Date(Date.now() + n * 86400000);
  return d.toISOString().slice(0, 10);
}

function Btn({ onClick, tone = 'primary', icon: Icon, children, disabled }) {
  const tones = {
    primary: 'bg-green-600 hover:bg-green-500 text-white',
    indigo: 'bg-indigo-600 hover:bg-indigo-500 text-white',
    ghost: 'bg-slate-800 border border-slate-700 text-slate-200 hover:bg-slate-700',
    outline: 'bg-slate-800 border border-indigo-500/30 text-indigo-300 hover:border-indigo-500/60',
    warn: 'bg-slate-800 border border-amber-500/30 text-amber-300 hover:border-amber-500/60',
  };
  return (
    <button onClick={onClick} disabled={disabled}
            className={`w-full flex items-center justify-center gap-2 py-3.5 rounded-xl text-sm font-semibold transition-colors disabled:opacity-50 ${tones[tone]}`}>
      {Icon && <Icon size={16} />} {children}
    </button>
  );
}

function Note({ icon: Icon = Hourglass, children }) {
  return (
    <div className="flex items-start gap-2 p-3 rounded-xl bg-slate-800/60 border border-slate-700 text-sm text-slate-300">
      <Icon size={16} className="shrink-0 mt-0.5 text-slate-400" />
      <span>{children}</span>
    </div>
  );
}

function RiskAcceptForm({ severity, onSubmit, onCancel, busy }) {
  const maxDays = severity === 'critical' ? 90 : 365;
  const [until, setUntil] = useState(daysFromNow(Math.min(30, maxDays)));
  const [why, setWhy] = useState('');
  const ok = why.trim().length >= 20 && until;
  return (
    <div className="space-y-2 p-3 rounded-xl bg-slate-900 border border-amber-500/30">
      <p className="text-sm text-amber-200 font-medium">Accept this risk temporarily</p>
      <p className="text-xs text-slate-400">It stays on the scorecard as failing until it's fixed or the acceptance expires (max {maxDays} days).</p>
      <label className="block text-xs text-slate-400">Expires
        <input type="date" value={until} min={daysFromNow(1)} max={daysFromNow(maxDays)} onChange={e => setUntil(e.target.value)}
               className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white" />
      </label>
      <label className="block text-xs text-slate-400">Why is this acceptable for now? (20+ characters)
        <textarea value={why} onChange={e => setWhy(e.target.value)} rows={3}
                  className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white" />
      </label>
      <div className="flex gap-2">
        <button onClick={onCancel} className="flex-1 py-2.5 rounded-lg bg-slate-800 text-slate-300 text-sm">Cancel</button>
        <button disabled={!ok || busy} onClick={() => onSubmit({ expires_at: new Date(`${until}T23:59:59Z`).toISOString(), justification: why.trim() })}
                className="flex-1 py-2.5 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm font-semibold">
          Accept risk
        </button>
      </div>
    </div>
  );
}

export default function RemediationActions({ control, onBack }) {
  const { workflow, can, me, statuses, openAttest } = useApp();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [riskOpen, setRiskOpen] = useState(false);

  const f = workflow.openFindingFor(control.id);
  const entry = statuses[control.id] ?? {};
  const passing = entry.status === 'pass';
  const severity = f?.severity ?? control.severity;
  const iDidWork = !!f?.remediated_by?.includes(me.user_id);
  const iSubmitted = f?.last_submitted_by === me.user_id;
  const assigneeName = f?.assigned_to_user_id
    ? (workflow.assignees.find(a => a.user_id === f.assigned_to_user_id)?.display_name
       ?? (f.assigned_to_user_id === me.user_id ? 'you' : f.assigned_to_user_id))
    : null;

  async function go(fn, back = false) {
    setBusy(true);
    try { await fn(); if (back) onBack(); } catch { /* toast already shown */ } finally { setBusy(false); }
  }

  const act = (action, extra, msg, back = true) => go(() => workflow.act(f.finding_id, action, extra, msg), back);

  const attestButton = can('attestation.create') && !passing && (
    <Btn tone="outline" icon={ShieldCheck} onClick={() => openAttest(control.id)} disabled={busy}>
      Covered by another platform? Attest it
    </Btn>
  );

  const riskButton = can('risk.accept') && f && !['risk_accepted', 'submitted_for_review'].includes(f.state) && (
    riskOpen
      ? <RiskAcceptForm severity={severity} busy={busy} onCancel={() => setRiskOpen(false)}
                        onSubmit={body => act('risk_accept', body, 'Risk accepted.')} />
      : <Btn tone="warn" icon={ShieldOff} onClick={() => setRiskOpen(true)} disabled={busy}>Accept risk…</Btn>
  );

  let body;

  if (!f) {
    if (passing) {
      body = (
        <>
          <Note icon={CheckCheck}>
            {entry.derived_from === 'attestation' ? `Covered by an attestation (${entry.notes?.replace('Attested: ', '')}).`
              : entry.derived_from === 'approved_finding' ? 'Fixed and approved.'
              : 'Passing.'}
          </Note>
          {(can('finding.remediate') || can('finding.assign')) && (
            <Btn tone="ghost" icon={Flag} disabled={busy} onClick={() => go(() => workflow.reportIssue(control.id), true)}>
              Report an issue
            </Btn>
          )}
        </>
      );
    } else {
      body = (
        <>
          {can('finding.remediate') && (
            <Btn icon={Play} disabled={busy} onClick={() => go(() => workflow.startFix(control.id))}>Start fixing</Btn>
          )}
          {!can('finding.remediate') && can('finding.assign') && (
            <Btn tone="ghost" icon={Flag} disabled={busy} onClick={() => go(() => workflow.reportIssue(control.id))}>
              Log it so it can be assigned
            </Btn>
          )}
          {attestButton}
          {!can('finding.remediate') && !can('finding.assign') && !can('attestation.create') && (
            <Note>You have view-only access here.</Note>
          )}
        </>
      );
    }
  } else if (['open', 'assigned', 'reopened'].includes(f.state)) {
    body = (
      <>
        <Note>{assigneeName ? `Assigned to ${assigneeName}. Not started yet.` : 'Logged, not assigned yet. Assign it from the Roadmap.'}</Note>
        {can('finding.remediate') && (
          <Btn icon={Play} disabled={busy} onClick={() => act('start', {}, "You're on it.", false)}>Start fixing</Btn>
        )}
        {attestButton}
        {riskButton}
      </>
    );
  } else if (f.state === 'in_progress') {
    body = (
      <>
        <Note>{`In progress${assigneeName ? ` — ${assigneeName}` : ''}.`}</Note>
        {can('finding.remediate') && (
          <>
            <textarea value={note} onChange={e => setNote(e.target.value)} rows={2}
                      placeholder="What did you change? (shown to the approver)"
                      className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white placeholder-slate-500" />
            <Btn icon={Send} disabled={busy}
                 onClick={() => act('submit', { note: note.trim() || null },
                   HIGH.has(severity) ? 'Sent for executive approval.' : 'Submitted.')}>
              {HIGH.has(severity) ? 'Submit fix for approval' : 'Submit fix'}
            </Btn>
          </>
        )}
        {riskButton}
      </>
    );
  } else if (f.state === 'submitted_for_review') {
    const canApproveHigh = can('finding.approve_close') && !iDidWork;
    const canClose = HIGH.has(severity) ? canApproveHigh
      : (can('finding.approve_close') || (can('finding.remediate') && iSubmitted));
    const lastNote = [...(f.events ?? [])].reverse().find(e => e.action === 'submit')?.note;
    body = (
      <>
        <Note>Fix submitted for review.{lastNote ? ` “${lastNote}”` : ''}</Note>
        {canClose && (
          <Btn icon={CheckCheck} disabled={busy} onClick={() => act('approve', {}, 'Approved. Control now passing.')}>
            {HIGH.has(severity) ? 'Approve & close' : 'Close it'}
          </Btn>
        )}
        {can('finding.approve_close') && !iDidWork && (
          <Btn tone="ghost" icon={Undo2} disabled={busy} onClick={() => act('reject', { note: 'Needs more work' }, 'Sent back.')}>Send back</Btn>
        )}
        {!canClose && (
          <Note icon={Hourglass}>
            {iDidWork && can('finding.approve_close')
              ? "You worked on this fix, so another executive has to approve it."
              : 'Waiting for an executive to approve.'}
          </Note>
        )}
      </>
    );
  } else if (f.state === 'risk_accepted') {
    body = (
      <>
        <Note icon={ShieldOff}>
          Risk accepted until {new Date(f.risk_accepted_until).toLocaleDateString()}{f.risk_acceptance_expired ? ' (expired)' : ''}.
          {f.risk_justification ? ` “${f.risk_justification}”` : ''}
        </Note>
        {can('finding.approve_close') && (
          <Btn tone="ghost" icon={RotateCcw} disabled={busy} onClick={() => act('reopen', {}, 'Reopened.', false)}>Reopen</Btn>
        )}
      </>
    );
  }

  return (
    <div className="space-y-2">
      {body}
      <button onClick={onBack} className="w-full py-3 text-slate-500 text-sm hover:text-slate-400">Back to dashboard</button>
    </div>
  );
}
