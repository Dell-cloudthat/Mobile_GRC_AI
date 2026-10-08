/**
 * AI Usage — which AI tools people use, how risky each one is, and what's
 * been decided. Works in demo mode (sample clinic) and connected mode.
 */
import { useMemo, useRef, useState } from 'react';
import { useApp } from '../../../SecurityOSApp';
import { errorMessage } from '../../../lib/errors';
import { LEVEL, LevelBar, RiskBadge, StatusChip, timeAgo } from './aiUi';
import {
  Sparkles, Upload, ChevronRight, AlertTriangle, Users, ShieldAlert, FileSpreadsheet, X, Info, RefreshCw,
} from 'lucide-react';

const FILTERS = [
  { id: 'attention', label: 'Needs attention', test: a => ['unreviewed', 'under_review'].includes(a.status) && ['critical', 'high'].includes(a.risk.level) },
  { id: 'open', label: 'Not reviewed', test: a => ['unreviewed', 'under_review'].includes(a.status) },
  { id: 'all', label: 'All', test: () => true },
  { id: 'decided', label: 'Decided', test: a => !['unreviewed', 'under_review'].includes(a.status) },
];

export default function AIUsageView() {
  const { aiState, reloadAi, openAiApp, ai } = useApp();
  const [filter, setFilter] = useState('attention');
  const [importOpen, setImportOpen] = useState(false);
  const inv = aiState.data;

  const apps = useMemo(() => {
    if (!inv) return [];
    const f = FILTERS.find(x => x.id === filter) ?? FILTERS[2];
    return inv.apps.filter(f.test);
  }, [inv, filter]);

  const s = inv?.summary;
  const onImport = inv?.can_import ? () => setImportOpen(true) : null;
  const sheet = importOpen && <ImportSheet onClose={() => setImportOpen(false)} onDone={reloadAi} />;

  // The import sheet renders beside <Shell> in every branch, so it (and its
  // result) survives the switch from the empty state to the list.
  let content;
  if (aiState.status === 'error') {
    content = (
      <div className="m-5 p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-sm text-red-200">
        {errorMessage(aiState.error)}
        <button onClick={reloadAi} className="mt-3 flex items-center gap-1.5 text-red-100 underline"><RefreshCw size={13} /> Try again</button>
      </div>
    );
  } else if (!inv) {
    content = <p className="p-5 text-sm text-slate-500">Loading AI usage…</p>;
  } else if (s.apps === 0) {
    content = <EmptyState canImport={inv.can_import} onImport={onImport} />;
  }
  if (content) {
    return <><Shell onImport={onImport} sample={null}>{content}</Shell>{sheet}</>;
  }

  return (
    <>
    <Shell onImport={onImport} sample={ai?.sample}>
      {/* Summary */}
      <div className="px-5 pt-5 pb-4 border-b border-slate-800 space-y-4">
        <div className="grid grid-cols-3 gap-2">
          <Stat label="AI apps found" value={s.apps} />
          <Stat label="People using AI" value={s.people} />
          <Stat label="Need attention" value={s.needs_attention} tone={s.needs_attention ? 'text-red-300' : 'text-green-300'} />
        </div>
        <LevelBar byLevel={s.by_level} />
        {s.regulated_data?.length > 0 && s.needs_attention > 0 && (
          <div className="flex gap-2 p-3 rounded-xl bg-red-500/10 border border-red-500/25 text-xs text-red-100">
            <ShieldAlert size={15} className="shrink-0 mt-0.5 text-red-300" />
            <span>
              Your business handles {s.regulated_data[0]}. {s.needs_attention} AI {s.needs_attention === 1 ? 'app' : 'apps'} could
              expose it without a signed data agreement.
            </span>
          </div>
        )}
        {s.still_in_use_after_block > 0 && (
          <div className="flex gap-2 p-3 rounded-xl bg-amber-500/10 border border-amber-500/25 text-xs text-amber-100">
            <AlertTriangle size={15} className="shrink-0 mt-0.5 text-amber-300" />
            <span>{s.still_in_use_after_block} blocked {s.still_in_use_after_block === 1 ? 'app is' : 'apps are'} still showing up in new scans.</span>
          </div>
        )}
        {s.top_departments?.length > 0 && (
          <p className="text-[11px] text-slate-500 flex items-center gap-1.5">
            <Users size={12} /> Most AI use: {s.top_departments.map(d => `${d.department} (${d.people})`).join(' · ')}
          </p>
        )}
      </div>

      {/* Filters */}
      <div className="px-5 pt-3 flex gap-2 overflow-x-auto no-scrollbar">
        {FILTERS.map(f => {
          const count = inv.apps.filter(f.test).length;
          return (
            <button key={f.id} onClick={() => setFilter(f.id)}
                    className={`shrink-0 px-3 py-1.5 rounded-full text-xs border transition-colors ${
                      filter === f.id ? 'bg-indigo-600 border-indigo-500 text-white' : 'bg-slate-900 border-slate-700 text-slate-300'}`}>
              {f.label} <span className="opacity-70">{count}</span>
            </button>
          );
        })}
      </div>

      {/* List */}
      <ul className="mt-2">
        {apps.length === 0 && (
          <li className="px-5 py-6 text-sm text-slate-500">Nothing here. {filter === 'attention' ? 'No open high-risk apps.' : ''}</li>
        )}
        {apps.map(a => (
          <li key={a.app_key}>
            <button onClick={() => openAiApp(a.app_key)}
                    className="w-full text-left px-5 py-3.5 border-b border-slate-800/80 hover:bg-slate-900 flex items-start gap-3">
              <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${LEVEL[a.risk.level].bar}`} />
              <span className="flex-1 min-w-0">
                <span className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-white truncate">{a.name}</span>
                  {!a.listed && <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">Unknown vendor</span>}
                </span>
                <span className="block text-[11px] text-slate-500 mt-0.5">
                  {a.category_label} · {a.user_count} {a.user_count === 1 ? 'person' : 'people'}
                </span>
                <span className="block text-xs text-slate-400 mt-1 line-clamp-2">{a.likely_use}</span>
                <span className="flex items-center gap-1.5 mt-2">
                  <RiskBadge risk={a.risk} />
                  <StatusChip status={a.status} label={a.status_label} />
                  {a.still_in_use && <span className="text-[10px] text-amber-300">Still in use</span>}
                </span>
              </span>
              <ChevronRight size={16} className="text-slate-600 mt-1 shrink-0" />
            </button>
          </li>
        ))}
      </ul>

      <p className="px-5 py-4 text-[10px] text-slate-600 flex gap-1.5">
        <Info size={11} className="shrink-0 mt-0.5" />
        <span>Last activity {timeAgo(s.last_seen)}. Vendor facts reviewed {inv.catalog_reviewed_at}. {inv.disclaimer}</span>
      </p>

    </Shell>
    {sheet}
    </>
  );
}

function Shell({ children, onImport, sample = null }) {
  return (
    <div className="flex flex-col min-h-full">
      <div className="px-5 pt-12 pb-4 border-b border-slate-800">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-white font-bold text-xl flex items-center gap-2">
              <Sparkles size={18} className="text-indigo-400" /> AI Usage
            </h1>
            <p className="text-slate-400 text-sm mt-0.5">Which AI tools your team uses, and the risk.</p>
            {sample && <p className="text-[11px] text-indigo-300 mt-1">Sample data: {sample.orgName}</p>}
          </div>
          {onImport && (
            <button onClick={onImport} title="Import discovery data"
                    className="shrink-0 h-10 px-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium flex items-center gap-1.5">
              <Upload size={15} /> Import
            </button>
          )}
        </div>
      </div>
      <div className="flex-1">{children}</div>
    </div>
  );
}

function Stat({ label, value, tone = 'text-white' }) {
  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-3">
      <p className={`text-2xl font-bold tabular-nums ${tone}`}>{value}</p>
      <p className="text-[10px] text-slate-500 mt-0.5 leading-tight">{label}</p>
    </div>
  );
}

function EmptyState({ canImport, onImport }) {
  return (
    <div className="p-5 space-y-4">
      <div className="p-4 rounded-2xl bg-slate-900 border border-slate-800">
        <p className="text-white font-semibold">No AI usage data yet</p>
        <p className="text-sm text-slate-400 mt-1">
          Import a list of the apps your people sign into and SecurityOS finds the AI tools, scores their risk and
          explains why your team is probably using each one.
        </p>
        {canImport
          ? <button onClick={onImport} className="mt-4 w-full py-3 rounded-xl bg-indigo-600 text-white text-sm font-semibold flex items-center justify-center gap-2"><Upload size={15} /> Import a file</button>
          : <p className="mt-3 text-xs text-slate-500">Ask your admin, engineer or MSP to import discovery data.</p>}
      </div>
      <WhereToGetIt />
    </div>
  );
}

function WhereToGetIt() {
  return (
    <div className="space-y-2 text-xs text-slate-400">
      <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Where to get the file</p>
      <p><span className="text-slate-200">Microsoft 365:</span> run the SecurityOS scanner script (read-only) for a list of every app people consented to, with departments and permissions.</p>
      <p><span className="text-slate-200">Microsoft Entra admin center:</span> Enterprise applications → Download (CSV).</p>
      <p><span className="text-slate-200">Defender for Cloud Apps:</span> Cloud discovery → Discovered apps → Export.</p>
      <p><span className="text-slate-200">Firewall / DNS filter:</span> export of domains visited, with a user column if you have one.</p>
      <p className="text-slate-500">Any CSV with an app name or domain column works. A user and department column makes the results much better.</p>
    </div>
  );
}

function ImportSheet({ onClose, onDone }) {
  const { ai, toast } = useApp();
  const fileRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function onFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true); setError(null); setResult(null);
    try {
      const text = await file.text();
      const r = await ai.importCsv(text, file.name);
      setResult(r);
      await onDone();
      toast?.(`Found ${r.apps_found} AI ${r.apps_found === 1 ? 'app' : 'apps'}.`, 'success');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  return (
    <div className="fixed inset-0 z-40 bg-black/60 flex items-end justify-center" onClick={onClose}>
      <div className="w-full max-w-lg max-h-[85vh] overflow-y-auto bg-slate-950 border-t border-slate-800 rounded-t-2xl p-5 space-y-4"
           onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <p className="text-white font-semibold flex items-center gap-2"><FileSpreadsheet size={16} /> Import discovery data</p>
          <button onClick={onClose} className="text-slate-400" aria-label="Close"><X size={18} /></button>
        </div>
        <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={onFile} />
        <button onClick={() => fileRef.current?.click()} disabled={busy}
                className="w-full py-3.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-semibold flex items-center justify-center gap-2">
          <Upload size={15} /> {busy ? 'Importing…' : 'Choose a CSV file'}
        </button>
        {error && <p className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-xl p-3">{error}</p>}
        {result && (
          <div className="text-sm text-slate-300 bg-slate-900 border border-slate-800 rounded-xl p-3 space-y-1.5">
            <p className="text-white font-medium">{result.apps_found} AI apps found in {result.rows} rows</p>
            {result.catalog_apps.length > 0 && <p className="text-xs">{result.catalog_apps.join(', ')}</p>}
            {result.possible_ai_apps.length > 0 && (
              <p className="text-xs text-amber-200">Possible AI apps we don't know yet: {result.possible_ai_apps.join(', ')}</p>
            )}
            <p className="text-[11px] text-slate-500">
              {result.ignored_rows} rows weren't AI apps{result.ignored_examples?.length ? ` (e.g. ${result.ignored_examples.slice(0, 3).join(', ')})` : ''}.
              Columns used: {Object.entries(result.columns_used).map(([k, v]) => `${k} = "${v}"`).join(', ')}.
            </p>
            <button onClick={onClose} className="mt-2 w-full py-2.5 rounded-lg bg-slate-800 text-slate-200 text-sm">See results</button>
          </div>
        )}
        <WhereToGetIt />
      </div>
    </div>
  );
}
