/**
 * AiGlanceCard   — one-line shadow AI status on the security profile.
 * AiPortfolioCard — MSP view: shadow AI across clients, and the offers it points to.
 */
import { useEffect, useState } from 'react';
import { useApp } from '../../../SecurityOSApp';
import { LevelBar } from './aiUi';
import { Sparkles, ChevronRight, MessagesSquare } from 'lucide-react';

export function AiGlanceCard() {
  const { aiState, setView } = useApp();
  const s = aiState?.data?.summary;
  if (!s) return null;
  const empty = s.apps === 0;
  return (
    <button onClick={() => setView('ai')}
            className="mx-5 mt-4 mb-4 w-[calc(100%-2.5rem)] text-left p-4 rounded-2xl bg-slate-900 border border-slate-800 hover:border-indigo-500/40 transition-colors">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-400 flex items-center gap-1.5"><Sparkles size={13} className="text-indigo-400" /> Shadow AI</p>
        <ChevronRight size={15} className="text-slate-600" />
      </div>
      {empty ? (
        <p className="text-sm text-slate-300 mt-1.5">No AI usage data yet. Import a discovery file to see which AI tools your team uses.</p>
      ) : (
        <>
          <p className="text-sm text-white mt-1.5">
            <span className="font-bold">{s.apps}</span> AI apps used by <span className="font-bold">{s.people}</span> people
            {s.needs_attention > 0
              ? <> · <span className="text-red-300 font-semibold">{s.needs_attention} need attention</span></>
              : <> · <span className="text-green-300">nothing urgent</span></>}
          </p>
          {s.top_risk && <p className="text-[11px] text-slate-500 mt-0.5">Highest risk: {s.top_risk}</p>}
          <div className="mt-3"><LevelBar byLevel={s.by_level} /></div>
        </>
      )}
    </button>
  );
}

export function AiPortfolioCard() {
  const { ai, switchTenant, setView } = useApp();
  const [data, setData] = useState(null);

  useEffect(() => {
    let live = true;
    if (!ai?.portfolio) return undefined;
    ai.portfolio().then(d => live && setData(d)).catch(() => live && setData(null));
    return () => { live = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ai?.key]);

  if (!ai?.portfolio || !data || data.totals.clients_scanned === 0) return null;
  const t = data.totals;

  return (
    <div className="px-5 py-5 border-b border-slate-800 space-y-4">
      <div>
        <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold flex items-center gap-1.5">
          <Sparkles size={12} className="text-indigo-400" /> Shadow AI across clients
        </p>
        <p className="text-sm text-white mt-1.5">
          {t.apps} AI apps at {t.clients_scanned} of {t.clients} clients · <span className="text-red-300 font-semibold">{t.needs_attention} need attention</span>
        </p>
        {ai.sample && <p className="text-[11px] text-indigo-300 mt-0.5">Sample clients</p>}
        <div className="mt-3"><LevelBar byLevel={t.by_level} /></div>
      </div>

      {data.opportunities.length > 0 && (
        <div className="space-y-2">
          <p className="text-[11px] text-slate-500">Conversations to have</p>
          {data.opportunities.slice(0, 3).map(o => (
            <div key={o.category} className="p-3 rounded-xl bg-indigo-500/10 border border-indigo-500/25">
              <p className="text-sm text-white font-medium flex items-center gap-2">
                <MessagesSquare size={14} className="text-indigo-300" /> {o.label} · {o.clients} {o.clients === 1 ? 'client' : 'clients'}
              </p>
              <p className="text-xs text-slate-300 mt-1">{o.offer}</p>
            </div>
          ))}
        </div>
      )}

      <div>
        <p className="text-[11px] text-slate-500 mb-1.5">By client</p>
        <ul className="rounded-xl border border-slate-800 divide-y divide-slate-800 overflow-hidden">
          {data.clients.map(c => (
            <li key={c.org_id}>
              <button
                disabled={ai.sample || !c.scanned}
                onClick={() => { switchTenant(c.org_id); setView('ai'); }}
                className="w-full px-3 py-2.5 flex items-center justify-between gap-3 text-left bg-slate-900 enabled:hover:bg-slate-800">
                <span className="min-w-0">
                  <span className="block text-sm text-white truncate">{c.name}</span>
                  <span className="block text-[11px] text-slate-500">
                    {c.scanned ? `${c.apps} apps · ${c.people} people${c.top_risk ? ` · top risk: ${c.top_risk}` : ''}` : 'Not scanned yet'}
                  </span>
                </span>
                {c.scanned && (
                  <span className={`shrink-0 text-xs font-semibold tabular-nums ${c.needs_attention ? 'text-red-300' : 'text-green-300'}`}>
                    {c.needs_attention} open
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>

      {t.clients_scanned >= 2 && data.top_apps.length > 0 && (
        <p className="text-[11px] text-slate-500">
          Most common: {data.top_apps.slice(0, 5).map(a => `${a.name} (${a.clients})`).join(' · ')}
        </p>
      )}
    </div>
  );
}
