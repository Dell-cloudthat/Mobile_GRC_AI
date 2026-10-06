/**
 * FixRoadmapView — Security Operations / Fix Roadmap
 *
 * Level 2 view: answers "What needs to be fixed, by whom, how, and when?"
 * This is where MSP engineers and customer administrators do the actual work.
 *
 * Shows: prioritized fix list grouped by severity, fix sessions,
 * per-fix assignment, effort, security impact, and framework tags.
 */
import { useState, useMemo, useCallback } from 'react';
import { useApp } from '../../SecurityOSApp';
import AwaitingYou from '../../api/AwaitingYou';
import { CATEGORY_LABEL } from '../../data/controls';
import { calculateImpact, toGrade } from '../../data/scoring';
import {
  Bot, ChevronDown, ChevronUp, Clock, UserPlus, Users,
  Zap, ShieldCheck, Target, CheckCheck, X, Layers,
  AlertTriangle, ChevronRight, RotateCcw, Calendar,
} from 'lucide-react';

// ── Constants ─────────────────────────────────────────────────────────────────
const SEV = {
  critical: { label: 'Critical', dot: '🔴', color: 'text-red-400',    bg: 'bg-red-500/12',    border: 'border-red-500/20',    badge: 'bg-red-500/15 text-red-400'    },
  high:     { label: 'High',     dot: '🟠', color: 'text-orange-400', bg: 'bg-orange-500/12', border: 'border-orange-500/20', badge: 'bg-orange-500/15 text-orange-400' },
  medium:   { label: 'Medium',   dot: '🟡', color: 'text-yellow-400', bg: 'bg-yellow-500/8',  border: 'border-yellow-500/15', badge: 'bg-yellow-500/15 text-yellow-400' },
  low:      { label: 'Low',      dot: '⚪', color: 'text-slate-400',  bg: 'bg-slate-900',     border: 'border-slate-800',     badge: 'bg-slate-800 text-slate-400'     },
};

const ASSIGNMENT_STATUSES = [
  'OPEN', 'ASSIGNED', 'IN_PROGRESS', 'BLOCKED', 'READY_FOR_VERIFICATION', 'ACCEPTED_RISK',
];

const FW_SHORT = {
  nist_csf_2: 'NIST', nist_ai_rmf: 'AI RMF', hipaa: 'HIPAA',
  pci_dss: 'PCI', ftc_safeguards: 'FTC', cyber_insurance: 'Insurance',
};

function effortLabel(mins) {
  if (!mins) return '~30 min';
  if (mins <= 5)  return '5 min';
  if (mins <= 15) return '15 min';
  if (mins <= 30) return '30 min';
  if (mins <= 45) return '45 min';
  if (mins <= 60) return '1 hr';
  if (mins <= 90) return '90 min';
  if (mins <= 120) return '2 hrs';
  return '4+ hrs';
}

function fwTags(control) {
  if (!control.framework_mappings) return [];
  return Object.keys(control.framework_mappings)
    .filter(k => control.framework_mappings[k]?.length > 0)
    .map(k => FW_SHORT[k] || k)
    .slice(0, 3);
}

// ── Assignment Panel (connected mode: pick a teammate who can remediate) ───────
function ApiAssignPanel({ assignment, onSave, onClose }) {
  const { workflow, can } = useApp();
  const [userId, setUserId] = useState(assignment?.userId ?? '');
  const [busy, setBusy] = useState(false);
  const people = workflow.assignees;

  if (!can('finding.assign')) {
    return (
      <div className="mx-4 mb-2 rounded-2xl bg-slate-800 border border-slate-700 p-4 text-xs text-slate-400 flex justify-between gap-3">
        <span>Only admins, executives, and MSP technicians can assign fixes.</span>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300"><X size={14} /></button>
      </div>
    );
  }

  return (
    <div className="mx-4 mb-2 rounded-2xl bg-slate-800 border border-slate-700 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-white flex items-center gap-1.5">
          <UserPlus size={13} className="text-indigo-400" /> Assign Fix
        </p>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300"><X size={14} /></button>
      </div>
      {people.length === 0 ? (
        <p className="text-xs text-slate-400">No one can be assigned yet. Invite an engineer from Settings → Team.</p>
      ) : (
        <select value={userId} onChange={e => setUserId(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
          <option value="">Choose a teammate…</option>
          {people.map(p => (
            <option key={p.user_id} value={p.user_id}>{p.display_name}{p.email ? ` (${p.email})` : ''}</option>
          ))}
        </select>
      )}
      <button
        disabled={!userId || busy}
        onClick={async () => { setBusy(true); try { await onSave({ userId }); onClose(); } catch { /* toast shown */ } finally { setBusy(false); } }}
        className="w-full py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold"
      >
        {busy ? 'Assigning…' : 'Assign'}
      </button>
    </div>
  );
}

function AssignPanel(props) {
  const { mode } = useApp();
  return mode === 'api' ? <ApiAssignPanel {...props} /> : <LocalAssignPanel {...props} />;
}

function LocalAssignPanel({ controlId, assignment, onSave, onClose }) {
  const [owner,   setOwner]   = useState(assignment?.owner   ?? '');
  const [dueDate, setDueDate] = useState(assignment?.dueDate ?? '');
  const [status,  setStatus]  = useState(assignment?.status  ?? 'ASSIGNED');

  function save() {
    if (!owner.trim()) { onSave(null); onClose(); return; }
    onSave({ owner: owner.trim(), dueDate, status });
    onClose();
  }

  return (
    <div className="mx-4 mb-2 rounded-2xl bg-slate-800 border border-slate-700 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-white flex items-center gap-1.5">
          <UserPlus size={13} className="text-indigo-400" /> Assign Fix
        </p>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300">
          <X size={14} />
        </button>
      </div>

      <div className="space-y-2">
        <div>
          <label className="text-[10px] text-slate-500 block mb-1">Assignee</label>
          <input
            value={owner}
            onChange={e => setOwner(e.target.value)}
            placeholder="Engineer name..."
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10px] text-slate-500 block mb-1">Due Date</label>
            <input
              type="date"
              value={dueDate}
              onChange={e => setDueDate(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
            />
          </div>
          <div>
            <label className="text-[10px] text-slate-500 block mb-1">Status</label>
            <select
              value={status}
              onChange={e => setStatus(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
            >
              {ASSIGNMENT_STATUSES.map(s => (
                <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="flex gap-2">
        <button
          onClick={save}
          className="flex-1 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold transition-colors"
        >
          Save
        </button>
        {assignment && (
          <button
            onClick={() => { onSave(null); onClose(); }}
            className="px-3 py-2 rounded-xl bg-slate-700 text-slate-400 text-xs hover:bg-slate-600 transition-colors"
          >
            Remove
          </button>
        )}
      </div>
    </div>
  );
}

// ── Fix Item ──────────────────────────────────────────────────────────────────
function FixItem({ control, impact, assignment, onFix, onAttest, onCopilot, onAssign, assignPanelOpen }) {
  const [expanded, setExpanded] = useState(false);
  const sev  = SEV[control.severity] || SEV.medium;
  const tags = fwTags(control);
  const isAttested = control.evidenceSource === 'attested_third_party';

  return (
    <div className="border-b border-slate-800/50 last:border-0">
      <div className={`px-4 py-4 ${assignPanelOpen ? 'bg-slate-800/30' : 'hover:bg-slate-800/20'} transition-colors`}>
        <div className="flex items-start gap-3">
          <span className="text-base leading-none shrink-0 mt-0.5">{sev.dot}</span>

          <div className="flex-1 min-w-0">
            {/* Title row */}
            <div className="flex items-start gap-2">
              <p className="text-white font-semibold text-sm leading-snug flex-1 min-w-0">{control.short_name}</p>
              {isAttested && (
                <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-indigo-600/20 text-indigo-400 border border-indigo-500/20 shrink-0 font-semibold">ATTESTED</span>
              )}
            </div>

            {/* Description */}
            <p className="text-slate-400 text-xs mt-0.5 leading-relaxed">{control.customerMessage}</p>

            {/* Badges */}
            <div className="flex flex-wrap items-center gap-1.5 mt-2">
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${sev.badge}`}>
                {sev.label}
              </span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 flex items-center gap-1">
                <Clock size={8} /> {effortLabel(control.estimated_minutes)}
              </span>
              {impact > 0 && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-green-500/12 text-green-400 flex items-center gap-1 font-semibold">
                  <Zap size={8} /> +{impact} pts
                </span>
              )}
              {tags.map(t => (
                <span key={t} className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800/80 text-slate-500">{t}</span>
              ))}
            </div>

            {/* Assignment status */}
            {assignment && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px]">
                <Users size={9} className="text-slate-500" />
                <span className="text-slate-400 font-medium">{assignment.owner}</span>
                {assignment.dueDate && (
                  <>
                    <span className="text-slate-700">·</span>
                    <span className="text-slate-500 flex items-center gap-0.5">
                      <Calendar size={8} />
                      {new Date(assignment.dueDate + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                    </span>
                  </>
                )}
                <span className={`px-1.5 py-0.5 rounded-full text-[9px] font-semibold ${
                  assignment.status === 'IN_PROGRESS'           ? 'bg-yellow-500/15 text-yellow-400' :
                  assignment.status === 'BLOCKED'               ? 'bg-red-500/15 text-red-400' :
                  assignment.status === 'READY_FOR_VERIFICATION'? 'bg-green-500/15 text-green-400' :
                  assignment.status === 'ACCEPTED_RISK'         ? 'bg-purple-500/15 text-purple-400' :
                  'bg-slate-700 text-slate-400'
                }`}>
                  {assignment.status?.replace(/_/g, ' ')}
                </span>
              </div>
            )}
          </div>

          <button onClick={() => setExpanded(e => !e)} className="text-slate-600 hover:text-slate-400 shrink-0 mt-0.5">
            {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        </div>

        {/* Action buttons */}
        <div className="flex gap-2 mt-3 ml-6">
          <button
            onClick={() => onFix(control.id)}
            className={`flex-1 py-2 text-xs rounded-xl font-semibold transition-colors ${
              isAttested
                ? 'bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700'
                : 'bg-indigo-600 hover:bg-indigo-500 text-white'
            }`}
          >
            {isAttested ? 'View Evidence' : 'Fix'}
          </button>
          <button
            onClick={() => onCopilot(control)}
            className="flex-1 py-2 text-xs rounded-xl bg-slate-800 border border-slate-700 text-indigo-400 font-medium hover:bg-slate-700 transition-colors flex items-center justify-center gap-1"
          >
            <Bot size={10} /> Copilot
          </button>
          <button
            onClick={onAssign}
            title="Assign"
            className={`w-8 h-[30px] rounded-xl border text-xs flex items-center justify-center transition-colors ${
              assignment
                ? 'bg-indigo-600/20 border-indigo-500/40 text-indigo-400'
                : 'bg-slate-800 border-slate-700 text-slate-500 hover:text-slate-300'
            }`}
          >
            <UserPlus size={12} />
          </button>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 ml-6 space-y-3 border-t border-slate-800/30 pt-3 bg-slate-900/30">
          {/* Why it matters */}
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 font-medium">Why it matters</p>
            <p className="text-xs text-slate-300 leading-relaxed">{control.customer_impact}</p>
          </div>

          {/* Quick steps */}
          {(control.remediation_steps || []).length > 0 && (
            <div>
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5 font-medium">Quick steps</p>
              <ol className="space-y-1.5">
                {control.remediation_steps.slice(0, 3).map((step, i) => (
                  <li key={i} className="flex gap-2 text-xs text-slate-300 leading-relaxed">
                    <span className="shrink-0 w-4 h-4 rounded-full bg-indigo-600/25 text-indigo-400 flex items-center justify-center text-[10px] font-bold">{i + 1}</span>
                    <span>{step}</span>
                  </li>
                ))}
              </ol>
              {(control.remediation_steps?.length ?? 0) > 3 && (
                <button onClick={() => onFix(control.id)} className="mt-2 text-xs text-indigo-400 hover:text-indigo-300">
                  See all {control.remediation_steps.length} steps →
                </button>
              )}
            </div>
          )}

          {/* Framework detail */}
          {tags.length > 0 && (
            <div>
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5 font-medium">Framework requirements</p>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(control.framework_mappings || {})
                  .filter(([, refs]) => refs?.length > 0)
                  .map(([fw, refs]) => (
                    <span key={fw} className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-400">
                      {FW_SHORT[fw] || fw}: {refs.slice(0, 2).join(', ')}
                    </span>
                  ))}
              </div>
            </div>
          )}

          {/* Evidence source for attested controls */}
          {isAttested && (
            <div className="rounded-xl bg-indigo-600/8 border border-indigo-500/20 px-3 py-2.5">
              <p className="text-[10px] text-indigo-400 font-semibold mb-0.5">Attested Coverage</p>
              <p className="text-xs text-indigo-200/70">This control is covered by third-party attestation. Connect a direct integration to raise evidence confidence from 70% to 90–100%.</p>
              <button onClick={() => onAttest(control.id)} className="mt-2 text-[10px] text-indigo-400 font-semibold hover:text-indigo-300">
                Update Attestation →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Fix Session Card ──────────────────────────────────────────────────────────
function FixSessionCard({ session, onStart }) {
  return (
    <div className="rounded-2xl bg-slate-800/60 border border-slate-700/60 p-4">
      <div className="flex items-start justify-between gap-2 mb-3">
        <div>
          <p className="text-white font-bold text-sm">{session.label}</p>
          <p className="text-slate-500 text-xs mt-0.5">
            {session.controls.length} fixes · ~{session.totalMinutes} min · +{session.totalImpact} pts estimated
          </p>
        </div>
        <Layers size={16} className="text-indigo-400 shrink-0 mt-0.5" />
      </div>

      <div className="flex flex-wrap gap-1.5 mb-3">
        {session.controls.slice(0, 4).map(c => (
          <span key={c.id} className="text-[10px] px-2 py-0.5 rounded-full bg-slate-700/60 text-slate-400 flex items-center gap-1">
            <span>{SEV[c.severity]?.dot || '⚪'}</span>
            {c.short_name}
          </span>
        ))}
        {session.controls.length > 4 && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-700/60 text-slate-500">
            +{session.controls.length - 4} more
          </span>
        )}
      </div>

      <button
        onClick={() => onStart(session)}
        className="w-full py-2 rounded-xl bg-indigo-600/20 border border-indigo-500/30 text-indigo-400 text-xs font-semibold hover:bg-indigo-600/30 transition-colors flex items-center justify-center gap-1.5"
      >
        <Target size={11} /> Start Fix Session
      </button>
    </div>
  );
}

// ── Severity Section ──────────────────────────────────────────────────────────
function SeveritySection({ sev, controls, impacts, assignments, assignPanelId, setAssignPanelId, onFix, onAttest, onCopilot, onAssignSave }) {
  const cfg = SEV[sev] || SEV.medium;
  if (controls.length === 0) return null;

  return (
    <div className="mb-2">
      <div className={`flex items-center gap-2 px-4 py-2 ${cfg.bg}`}>
        <span className="text-sm">{cfg.dot}</span>
        <span className={`text-xs font-bold uppercase tracking-wider ${cfg.color}`}>{cfg.label}</span>
        <span className="text-xs text-slate-600">— {controls.length} fix{controls.length !== 1 ? 'es' : ''}</span>
      </div>

      {controls.map(c => (
        <div key={c.id}>
          <FixItem
            control={c}
            impact={impacts[c.id] ?? 0}
            assignment={assignments[c.id]}
            assignPanelOpen={assignPanelId === c.id}
            onFix={onFix}
            onAttest={onAttest}
            onCopilot={onCopilot}
            onAssign={() => setAssignPanelId(prev => prev === c.id ? null : c.id)}
          />
          {assignPanelId === c.id && (
            <AssignPanel
              controlId={c.id}
              assignment={assignments[c.id]}
              onSave={data => onAssignSave(c.id, data)}
              onClose={() => setAssignPanelId(null)}
            />
          )}
        </div>
      ))}
    </div>
  );
}

// ── Main View ─────────────────────────────────────────────────────────────────
export default function FixRoadmapView() {
  const {
    scoring, profile, statuses, catalog,
    openFix, openAttest, openCopilotWithPrompt,
    assignments, setAssignment,
  } = useApp();

  const { totalScore, issues, passing, allControls } = scoring;
  const [activeSession, setActiveSession] = useState(null);
  const [assignPanelId, setAssignPanelId] = useState(null);
  const [showSessions, setShowSessions] = useState(true);

  // Compute impact per issue (expensive, memoized)
  const impacts = useMemo(() => {
    const map = {};
    for (const c of issues) {
      map[c.id] = calculateImpact(c.id, statuses, profile, catalog);
    }
    return map;
  }, [issues, statuses, profile, catalog]);

  // Target score: current + sum of critical+high impacts
  const highValueImpact = issues
    .filter(c => c.severity === 'critical' || c.severity === 'high')
    .reduce((s, c) => s + (impacts[c.id] || 0), 0);
  const targetScore = Math.min(100, totalScore + highValueImpact);

  // Totals
  const totalMinutes = issues.reduce((s, c) => s + (c.estimated_minutes || 30), 0);
  const totalImpact  = Object.values(impacts).reduce((s, v) => s + v, 0);

  // Fix sessions: group by category where 2+ issues share a category
  const sessions = useMemo(() => {
    const byCat = {};
    for (const c of issues) {
      if (!byCat[c.category]) byCat[c.category] = [];
      byCat[c.category].push(c);
    }
    return Object.entries(byCat)
      .filter(([, cs]) => cs.length >= 2)
      .map(([cat, cs]) => ({
        id: cat,
        label: (CATEGORY_LABEL[cat] || cat) + ' Hardening',
        controls: cs,
        totalMinutes: cs.reduce((s, c) => s + (c.estimated_minutes || 30), 0),
        totalImpact: cs.reduce((s, c) => s + (impacts[c.id] || 0), 0),
      }))
      .sort((a, b) => b.totalImpact - a.totalImpact)
      .slice(0, 3);
  }, [issues, impacts]);

  // Filter by active session
  const visibleIssues = activeSession
    ? issues.filter(c => c.category === activeSession.id)
    : issues;

  const byGroup = {
    critical: visibleIssues.filter(c => c.severity === 'critical'),
    high:     visibleIssues.filter(c => c.severity === 'high'),
    medium:   visibleIssues.filter(c => c.severity === 'medium'),
    low:      visibleIssues.filter(c => c.severity === 'low'),
  };

  // Attested (passing but attested — not in issues list)
  const attestedPassing = passing.filter(c => c.evidenceSource === 'attested_third_party');

  function handleCopilot(control) {
    openCopilotWithPrompt(
      `Tell me how to fix "${control.name}" — give me step-by-step remediation instructions for this control.`
    );
  }

  const handleAssignSave = useCallback((controlId, data) => {
    setAssignment(controlId, data);
  }, [setAssignment]);

  function fmtTime(mins) {
    if (mins < 60) return `${mins} min`;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return m > 0 ? `${h}h ${m}m` : `${h} hr${h > 1 ? 's' : ''}`;
  }

  return (
    <div className="flex flex-col min-h-full">
      {/* Header */}
      <div className="px-5 pt-12 pb-4 border-b border-slate-800">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-widest font-medium">Fix Roadmap</p>
            <h1 className="text-white font-bold text-xl mt-0.5">
              {profile.businessName || 'Your Business'}
            </h1>
          </div>
          {activeSession && (
            <button
              onClick={() => setActiveSession(null)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-indigo-600/20 border border-indigo-500/30 text-indigo-400 text-xs font-medium"
            >
              <X size={11} /> Clear session
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">

        {/* Stats bar */}
        <div className="px-5 py-4 border-b border-slate-800 grid grid-cols-4 gap-2 text-center">
          <div>
            <p className="text-xl font-bold text-white tabular-nums">{totalScore}</p>
            <p className="text-[10px] text-slate-500">Current</p>
          </div>
          <div className="flex items-center justify-center">
            <ChevronRight size={16} className="text-slate-700" />
          </div>
          <div>
            <p className={`text-xl font-bold tabular-nums ${targetScore > totalScore ? 'text-green-400' : 'text-slate-400'}`}>
              {targetScore}
            </p>
            <p className="text-[10px] text-slate-500">Target</p>
          </div>
          <div>
            <p className="text-xl font-bold text-slate-300 tabular-nums">{issues.length}</p>
            <p className="text-[10px] text-slate-500">Open</p>
          </div>
        </div>

        {/* Total effort + impact summary */}
        {issues.length > 0 && (
          <div className="px-5 py-3 border-b border-slate-800 flex items-center gap-4 text-xs text-slate-500">
            <span className="flex items-center gap-1">
              <Clock size={11} /> Est. {fmtTime(totalMinutes)} total
            </span>
            <span className="text-slate-700">·</span>
            <span className="flex items-center gap-1">
              <Zap size={11} /> +{totalImpact} pts if all fixed
            </span>
          </div>
        )}

        {/* Work waiting on this person (connected mode) */}
        <AwaitingYou />

        {/* Fix sessions */}
        {sessions.length > 0 && (
          <div className="px-4 pt-4 pb-2">
            <button
              onClick={() => setShowSessions(s => !s)}
              className="flex items-center justify-between w-full mb-3"
            >
              <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium flex items-center gap-1.5">
                <Layers size={11} className="text-indigo-400" /> Fix Sessions
              </p>
              {showSessions ? <ChevronUp size={13} className="text-slate-600" /> : <ChevronDown size={13} className="text-slate-600" />}
            </button>
            {showSessions && (
              <div className="space-y-2 mb-2">
                {sessions.map(s => (
                  <FixSessionCard
                    key={s.id}
                    session={s}
                    onStart={session => {
                      setActiveSession(session);
                      setShowSessions(false);
                    }}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Active session banner */}
        {activeSession && (
          <div className="mx-4 mb-3 px-4 py-2 rounded-xl bg-indigo-600/15 border border-indigo-500/30 flex items-center gap-2">
            <Target size={13} className="text-indigo-400 shrink-0" />
            <p className="text-xs text-indigo-300 flex-1 font-medium">Session: {activeSession.label}</p>
            <span className="text-[10px] text-indigo-400">{visibleIssues.length} fixes</span>
          </div>
        )}

        {/* Empty state */}
        {visibleIssues.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
            <div className="text-4xl mb-4">🎉</div>
            <p className="text-white font-bold text-lg mb-2">
              {activeSession ? `No open fixes in ${activeSession.label}` : 'All clear!'}
            </p>
            <p className="text-slate-400 text-sm">
              {activeSession
                ? 'All controls in this session are passing.'
                : 'All controls are passing. Your security posture is excellent.'}
            </p>
            {activeSession && (
              <button
                onClick={() => setActiveSession(null)}
                className="mt-4 text-indigo-400 text-sm hover:text-indigo-300"
              >
                View all fixes →
              </button>
            )}
          </div>
        )}

        {/* Fix list grouped by severity */}
        <div className="pb-4">
          {(['critical', 'high', 'medium', 'low']).map(sev => (
            <SeveritySection
              key={sev}
              sev={sev}
              controls={byGroup[sev]}
              impacts={impacts}
              assignments={assignments}
              assignPanelId={assignPanelId}
              setAssignPanelId={setAssignPanelId}
              onFix={openFix}
              onAttest={openAttest}
              onCopilot={handleCopilot}
              onAssignSave={handleAssignSave}
            />
          ))}
        </div>

        {/* Attested passing controls */}
        {attestedPassing.length > 0 && (
          <div className="mb-4">
            <div className="flex items-center gap-2 px-4 py-2 bg-indigo-500/8">
              <ShieldCheck size={13} className="text-indigo-400" />
              <span className="text-xs font-bold uppercase tracking-wider text-indigo-400">Attested</span>
              <span className="text-xs text-slate-600">— {attestedPassing.length} control{attestedPassing.length !== 1 ? 's' : ''}</span>
            </div>
            {attestedPassing.map(c => (
              <div key={c.id} className="px-4 py-3 border-b border-slate-800/40 hover:bg-slate-800/20 transition-colors">
                <div className="flex items-center gap-3">
                  <ShieldCheck size={14} className="text-indigo-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-slate-300 text-sm font-medium">{c.short_name}</p>
                    <p className="text-slate-500 text-xs mt-0.5">{c.notes || 'Third-party attested coverage'}</p>
                  </div>
                  <button
                    onClick={() => openFix(c.id)}
                    className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors shrink-0"
                  >
                    View
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Passing count footer */}
        {passing.length > 0 && (
          <div className="px-5 py-3 border-t border-slate-800">
            <p className="text-xs text-slate-600 flex items-center gap-1.5">
              <CheckCheck size={12} className="text-green-500" />
              {passing.length} control{passing.length !== 1 ? 's' : ''} passing — {toGrade(totalScore)} posture
            </p>
          </div>
        )}

        <div className="h-4" />
      </div>
    </div>
  );
}
