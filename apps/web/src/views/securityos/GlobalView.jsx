import { useMemo, useState } from 'react';
import { useApp, ScoreRing } from '../../SecurityOSApp';
import { calculateScore, toGrade, toColor } from '../../data/scoring';
import { STATUS, SEVERITY_DOT } from '../../data/controls';
import { AiPortfolioCard } from './ai/AiCards';
import { Building2, ChevronDown, ChevronRight, ChevronUp, Globe, Plus } from 'lucide-react';

const COLOR_TEXT = {
  green:  'text-green-400',
  blue:   'text-indigo-400',
  yellow: 'text-yellow-400',
  orange: 'text-orange-400',
  red:    'text-red-400',
};

const COLOR_BG = {
  green:  'bg-green-500/10',
  blue:   'bg-indigo-500/10',
  yellow: 'bg-yellow-500/10',
  orange: 'bg-orange-500/10',
  red:    'bg-red-500/10',
};

function statusPill(status) {
  if (status === STATUS.FAIL) return { label: 'Failing', cls: 'bg-red-500/10 text-red-400 border border-red-500/20' };
  if (status === STATUS.UNKNOWN) return { label: 'Unverified', cls: 'bg-slate-800 text-slate-400 border border-slate-700' };
  return { label: 'Open', cls: 'bg-slate-800 text-slate-400 border border-slate-700' };
}

export default function GlobalView() {
  const { tenants, catalog, activeTenantId, switchTenant, addTenant, openFixForTenant, setView } = useApp();
  const [expandedFixId, setExpandedFixId] = useState(null);

  const model = useMemo(() => {
    const tenantSummaries = (tenants || []).map(t => {
      const profile = t.profile ?? {};
      const statuses = t.statuses ?? {};
      const name = (profile.businessName || t.name || 'Tenant').trim();
      const scoring = calculateScore(statuses, profile, catalog);
      return { id: t.id, name, scoring };
    });

    const n = tenantSummaries.length;
    const avgScore = n ? Math.round(tenantSummaries.reduce((s, x) => s + (x.scoring.totalScore || 0), 0) / n) : 0;
    const globalColor = toColor(avgScore);

    const overlap = new Map();
    for (const t of tenantSummaries) {
      for (const issue of t.scoring.issues || []) {
        const key = issue.id;
        const existing = overlap.get(key) ?? { control: issue, tenants: [] };
        existing.tenants.push({ tenantId: t.id, tenantName: t.name, status: issue.status });
        overlap.set(key, existing);
      }
    }

    const sevOrder = { critical: 0, high: 1, medium: 2, low: 3 };
    const overlappingFixes = [...overlap.values()]
      .filter(x => x.tenants.length >= 2)
      .sort((a, b) => {
        if (b.tenants.length !== a.tenants.length) return b.tenants.length - a.tenants.length;
        return (sevOrder[a.control.severity] ?? 9) - (sevOrder[b.control.severity] ?? 9);
      });

    const mostAtRisk = [...tenantSummaries].sort((a, b) => (a.scoring.totalScore ?? 0) - (b.scoring.totalScore ?? 0))[0] ?? null;
    const best = [...tenantSummaries].sort((a, b) => (b.scoring.totalScore ?? 0) - (a.scoring.totalScore ?? 0))[0] ?? null;

    return { tenantSummaries, avgScore, globalColor, overlappingFixes, mostAtRisk, best };
  }, [tenants, catalog]);

  const globalText = COLOR_TEXT[model.globalColor] || COLOR_TEXT.blue;
  const globalBg = COLOR_BG[model.globalColor] || COLOR_BG.blue;

  function createTenant() {
    const name = window.prompt('Tenant name (company/site/client)')?.trim();
    if (!name) return;
    addTenant(name, 'demo');
  }

  return (
    <div className="flex flex-col min-h-full">
      {/* Header */}
      <div className="px-5 pt-12 pb-4 border-b border-slate-800">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-white font-bold text-xl flex items-center gap-2">
              <Globe size={18} className="text-indigo-400" />
              Global Overview
            </h1>
            <p className="text-slate-400 text-sm mt-0.5">
              Compare tenants and spot overlapping fixes at a glance.
            </p>
          </div>
          <button
            onClick={createTenant}
            className="shrink-0 w-10 h-10 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white flex items-center justify-center transition-colors"
            title="Add tenant"
          >
            <Plus size={18} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <AiPortfolioCard />
        {/* Global score */}
        <div className="px-5 pt-6 pb-5 border-b border-slate-800">
          <div className="flex items-center gap-4">
            <div className="relative shrink-0">
              <ScoreRing score={model.avgScore} size={92} strokeWidth={7} />
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-2xl font-bold text-white tabular-nums">{model.avgScore}</span>
              </div>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs text-slate-500 uppercase tracking-widest">Global Score (avg)</p>
              <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-full text-sm font-semibold mt-1 ${globalBg} ${globalText}`}>
                {toGrade(model.avgScore)}
                <span className="text-slate-600">·</span>
                {model.tenantSummaries.length} tenant{model.tenantSummaries.length !== 1 ? 's' : ''}
              </div>
              <div className="text-xs text-slate-500 mt-2">
                {model.best && (
                  <span>
                    Best: <span className="text-slate-300 font-medium">{model.best.name}</span> ({model.best.scoring.totalScore}/100)
                  </span>
                )}
                {model.best && model.mostAtRisk && <span className="text-slate-700 mx-2">·</span>}
                {model.mostAtRisk && (
                  <span>
                    At risk: <span className="text-slate-300 font-medium">{model.mostAtRisk.name}</span> ({model.mostAtRisk.scoring.totalScore}/100)
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Tenants list */}
        <div className="px-5 pt-5 pb-2">
          <p className="text-xs text-slate-500 uppercase tracking-widest font-medium">Tenants</p>
        </div>
        <div className="border-y border-slate-800 bg-slate-900">
          {model.tenantSummaries.map(t => {
            const active = t.id === activeTenantId;
            const issues = (t.scoring.summary?.failing ?? 0) + (t.scoring.summary?.unknown ?? 0);
            const color = toColor(t.scoring.totalScore);
            const cText = COLOR_TEXT[color] || COLOR_TEXT.blue;
            const cBg = COLOR_BG[color] || COLOR_BG.blue;
            return (
              <button
                key={t.id}
                onClick={() => { switchTenant(t.id); setView('home'); }}
                className="w-full flex items-center gap-3 px-5 py-4 border-b border-slate-800 last:border-0 hover:bg-slate-800/40 transition-colors text-left"
              >
                <div className="w-9 h-9 rounded-xl bg-slate-800 flex items-center justify-center shrink-0">
                  <Building2 size={16} className={active ? 'text-indigo-400' : 'text-slate-400'} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-white text-sm font-semibold truncate">{t.name}</p>
                    {active && <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-600/20 text-indigo-300 border border-indigo-500/20">Active</span>}
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {issues === 0 ? 'No open issues' : `${issues} open issue${issues !== 1 ? 's' : ''}`} · {t.scoring.verifiedPct}% verified
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className={`text-xs font-semibold px-2 py-1 rounded-full ${cBg} ${cText}`}>
                    {t.scoring.totalScore}/100
                  </span>
                  <ChevronRight size={14} className="text-slate-600" />
                </div>
              </button>
            );
          })}
        </div>

        {/* Overlapping fixes */}
        <div className="px-5 pt-6 pb-2">
          <p className="text-xs text-slate-500 uppercase tracking-widest font-medium">Overlapping fixes</p>
        </div>

        {model.overlappingFixes.length === 0 ? (
          <div className="mx-5 mb-8 bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-slate-300 text-sm font-semibold">No overlaps yet.</p>
            <p className="text-slate-500 text-xs mt-1">
              When the same control is failing or unverified across multiple tenants, it will appear here.
            </p>
          </div>
        ) : (
          <div className="mx-5 mb-6 bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            {model.overlappingFixes.slice(0, 10).map(item => {
              const open = expandedFixId === item.control.id;
              return (
                <div key={item.control.id} className="border-b border-slate-800 last:border-0">
                  <button
                    onClick={() => setExpandedFixId(open ? null : item.control.id)}
                    className="w-full px-4 py-4 flex items-center gap-3 text-left hover:bg-slate-800/40 transition-colors"
                  >
                    <span className="text-xl shrink-0 leading-none">{SEVERITY_DOT[item.control.severity] || '⚪'}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-white text-sm font-semibold truncate">{item.control.short_name}</p>
                      <p className="text-xs text-slate-500 mt-0.5 truncate">
                        {item.tenants.length} tenants impacted
                      </p>
                    </div>
                    <span className="text-slate-500 shrink-0">
                      {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                    </span>
                  </button>

                  {open && (
                    <div className="px-4 pb-4">
                      <div className="flex flex-wrap gap-2">
                        {item.tenants.map(t => {
                          const p = statusPill(t.status);
                          return (
                            <button
                              key={t.tenantId}
                              onClick={() => openFixForTenant(t.tenantId, item.control.id)}
                              className={`text-xs px-2.5 py-1.5 rounded-full flex items-center gap-2 transition-colors hover:opacity-90 ${p.cls}`}
                              title="Open fix in this tenant"
                            >
                              <span className="font-semibold">{t.tenantName}</span>
                              <span className="text-slate-600">·</span>
                              <span>{p.label}</span>
                            </button>
                          );
                        })}
                      </div>
                      <p className="text-[10px] text-slate-600 mt-3">
                        Tap a tenant to jump directly into the fix steps for that tenant.
                      </p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div className="h-4" />
      </div>
    </div>
  );
}

