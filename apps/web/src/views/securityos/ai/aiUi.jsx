/** Shared building blocks for the AI Usage screens. */

export const LEVEL = {
  critical: { label: 'Critical', text: 'text-red-300',    bg: 'bg-red-500/15',    border: 'border-red-500/40',    bar: 'bg-red-500' },
  high:     { label: 'High',     text: 'text-orange-300', bg: 'bg-orange-500/15', border: 'border-orange-500/40', bar: 'bg-orange-500' },
  medium:   { label: 'Medium',   text: 'text-yellow-300', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', bar: 'bg-yellow-500' },
  low:      { label: 'Low',      text: 'text-green-300',  bg: 'bg-green-500/10',  border: 'border-green-500/30',  bar: 'bg-green-500' },
};

const STATUS = {
  unreviewed:        'bg-slate-800 text-slate-300 border-slate-700',
  under_review:      'bg-indigo-500/15 text-indigo-200 border-indigo-500/30',
  approved:          'bg-green-500/15 text-green-200 border-green-500/30',
  approved_business: 'bg-green-500/15 text-green-200 border-green-500/30',
  blocked:           'bg-red-500/15 text-red-200 border-red-500/30',
  risk_accepted:     'bg-amber-500/15 text-amber-200 border-amber-500/30',
};

export function RiskBadge({ risk, size = 'sm' }) {
  const l = LEVEL[risk.level] ?? LEVEL.medium;
  const big = size === 'lg';
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border ${l.bg} ${l.border} ${l.text} ${big ? 'px-3 py-1 text-sm' : 'px-2 py-0.5 text-[11px]'} font-semibold tabular-nums`}>
      {l.label} · {risk.score}
    </span>
  );
}

export function StatusChip({ status, label }) {
  return (
    <span className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATUS[status] ?? STATUS.unreviewed}`}>
      {label}
    </span>
  );
}

export function LevelBar({ byLevel }) {
  const total = Object.values(byLevel).reduce((s, n) => s + n, 0) || 1;
  return (
    <div>
      <div className="flex h-2 rounded-full overflow-hidden bg-slate-800">
        {['critical', 'high', 'medium', 'low'].map(l => byLevel[l] > 0 && (
          <div key={l} className={LEVEL[l].bar} style={{ width: `${(byLevel[l] / total) * 100}%` }} />
        ))}
      </div>
      <div className="flex justify-between mt-1.5 text-[10px] text-slate-500">
        {['critical', 'high', 'medium', 'low'].map(l => (
          <span key={l}><span className={LEVEL[l].text}>{byLevel[l]}</span> {LEVEL[l].label.toLowerCase()}</span>
        ))}
      </div>
    </div>
  );
}

export function Section({ title, children, right = null }) {
  return (
    <section className="px-5 py-4 border-b border-slate-800">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

export function timeAgo(iso) {
  if (!iso) return '—';
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days} days ago`;
  return new Date(iso).toLocaleDateString();
}

export const SOURCE_LABEL = { csv: 'CSV import', m365: 'Microsoft 365' };
