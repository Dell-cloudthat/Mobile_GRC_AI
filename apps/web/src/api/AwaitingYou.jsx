/**
 * "Awaiting you" inbox (connected mode): the work that needs THIS person now.
 *   - Fixes waiting for your approval (you can approve and didn't do the work)
 *   - Fixes assigned to you that are in progress or not started
 *   - Fixes you submitted that are waiting on someone else
 */
import { useApp } from '../SecurityOSApp';
import { getControlById } from '../data/controls';
import { CheckCheck, Wrench, Hourglass, ChevronRight } from 'lucide-react';

const HIGH = new Set(['critical', 'high']);

function canClose(f, me, can) {
  if (HIGH.has(f.severity)) return can('finding.approve_close') && !f.remediated_by?.includes(me.user_id);
  return can('finding.approve_close') || (can('finding.remediate') && f.last_submitted_by === me.user_id);
}

export default function AwaitingYou() {
  const { mode, workflow, me, can, openFix } = useApp();
  if (mode !== 'api') return null;

  const open = workflow.openFindings;
  const approve = open.filter(f => f.state === 'submitted_for_review' && canClose(f, me, can));
  const mine = open.filter(f => ['assigned', 'reopened', 'in_progress', 'open'].includes(f.state) && f.assigned_to_user_id === me.user_id);
  const waiting = open.filter(f => f.state === 'submitted_for_review' && f.last_submitted_by === me.user_id && !canClose(f, me, can));

  const groups = [
    { key: 'approve', title: 'Needs your approval', icon: CheckCheck, tone: 'text-green-400', items: approve },
    { key: 'mine', title: 'Your fixes', icon: Wrench, tone: 'text-indigo-300', items: mine },
    { key: 'waiting', title: 'Waiting on approval', icon: Hourglass, tone: 'text-slate-400', items: waiting },
  ].filter(g => g.items.length);

  if (!groups.length) return null;

  return (
    <div className="mx-4 mt-4 rounded-2xl bg-slate-900 border border-indigo-500/30 overflow-hidden">
      <p className="px-4 pt-3 pb-2 text-[11px] uppercase tracking-wider text-indigo-300 font-semibold">Awaiting you</p>
      {groups.map(({ key, title, icon: Icon, tone, items }) => (
        <div key={key} className="border-t border-slate-800">
          <p className={`px-4 pt-2 text-xs font-medium flex items-center gap-1.5 ${tone}`}><Icon size={13} /> {title}</p>
          {items.map(f => {
            const controlId = f.control_ids[0];
            const control = getControlById(controlId);
            return (
              <button key={f.finding_id} onClick={() => openFix(controlId)}
                      className="w-full flex items-center justify-between gap-2 px-4 py-2.5 text-left hover:bg-slate-800/60">
                <span className="min-w-0">
                  <span className="block text-sm text-white truncate">{control?.short_name ?? f.title}</span>
                  <span className="block text-[11px] text-slate-500 capitalize">{f.severity} · {f.state.replace(/_/g, ' ')}</span>
                </span>
                <ChevronRight size={15} className="text-slate-600 shrink-0" />
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
