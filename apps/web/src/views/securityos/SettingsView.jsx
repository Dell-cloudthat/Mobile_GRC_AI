import { useState } from 'react';
import { useApp } from '../../SecurityOSApp';
import { STATUS, CONTROLS_CATALOG } from '../../data/controls';
import { buildDemoStatuses } from '../../data/scoring';
import { ShieldCheck, RefreshCw, Trash2, ChevronRight } from 'lucide-react';
import { AccountSection, TeamSection, AuditSection } from '../../api/TeamPanel';

const INDUSTRIES = [
  'Medical / Dental Practice', 'Mental Health / Therapy', 'Legal Services',
  'Accounting / CPA', 'Financial Advisory', 'Insurance Agency', 'Real Estate',
  'Consulting', 'Marketing / Creative Agency', 'IT / MSP', 'E-commerce',
  'Construction / Contracting', 'Other Professional Services',
];

const SENSITIVE_DATA = [
  { id: 'phi',      label: 'Health / Medical Records',  flag: 'HIPAA'   },
  { id: 'pii',      label: 'Customer Personal Info',    flag: null       },
  { id: 'payment',  label: 'Payment Card Data',         flag: 'PCI DSS' },
  { id: 'financial',label: 'Financial Records',         flag: null       },
  { id: 'legal',    label: 'Legal Documents',           flag: null       },
  { id: 'federal',  label: 'Federal / Gov Data',        flag: 'CMMC'    },
];

const EMAIL_PROVIDERS = ['Microsoft 365', 'Google Workspace', 'Other', 'On-premise'];

function Row({ label, children }) {
  return (
    <div className="border-b border-slate-800 px-5 py-4 last:border-0">
      <p className="text-xs text-slate-500 mb-2">{label}</p>
      {children}
    </div>
  );
}

export default function SettingsView() {
  const { profile, setProfile, statuses, updateStatus, scoring, mode, can } = useApp();
  const isApi = mode === 'api';
  const readOnlyProfile = isApi && !can('org.manage');
  const [saved, setSaved] = useState(false);

  function upd(key, val) { setProfile(p => ({ ...p, [key]: val })); }

  function save() { setSaved(true); setTimeout(() => setSaved(false), 1800); }

  function resetDemo() {
    if (!window.confirm('Reset all control statuses to demo data?')) return;
    const d = buildDemoStatuses();
    Object.entries(d).forEach(([id, entry]) => updateStatus(id, entry.status, entry.notes, entry.evidence_source));
  }

  function markAll() {
    if (!window.confirm('Mark all 25 controls as passing?')) return;
    CONTROLS_CATALOG.forEach(c => updateStatus(c.id, STATUS.PASS, null, 'manual'));
  }

  function clearAll() {
    if (!window.confirm('Clear all data and restart? This cannot be undone.')) return;
    localStorage.removeItem('securityos_v2');
    window.location.reload();
  }

  return (
    <div className="flex flex-col min-h-full">
      {/* Header */}
      <div className="px-5 pt-12 pb-4 border-b border-slate-800">
        <h1 className="text-white font-bold text-xl">Settings</h1>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Score summary */}
        <div className="px-5 py-4 border-b border-slate-800">
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="bg-slate-800 rounded-xl p-3">
              <p className="text-2xl font-bold text-white">{scoring.totalScore}</p>
              <p className="text-xs text-slate-500 mt-0.5">Score</p>
            </div>
            <div className="bg-green-500/10 rounded-xl p-3">
              <p className="text-2xl font-bold text-green-400">{scoring.summary.passing}</p>
              <p className="text-xs text-slate-500 mt-0.5">Passing</p>
            </div>
            <div className="bg-red-500/10 rounded-xl p-3">
              <p className="text-2xl font-bold text-red-400">{scoring.summary.failing + scoring.summary.unknown}</p>
              <p className="text-xs text-slate-500 mt-0.5">Issues</p>
            </div>
          </div>
        </div>

        {/* Business profile */}
        <div className="mt-4">
          <p className="px-5 text-xs text-slate-500 uppercase tracking-wider mb-2">Business Profile</p>
          {readOnlyProfile && <p className="px-5 text-[11px] text-slate-500 mb-2">Only an admin can edit the profile.</p>}
          <fieldset disabled={readOnlyProfile} className={`bg-slate-900 border-y border-slate-800 ${readOnlyProfile ? 'opacity-70' : ''}`}>
            <Row label="Business Name">
              <input
                value={profile.businessName}
                onChange={e => upd('businessName', e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              />
            </Row>

            {!isApi && (<>
            <Row label="Owner / Attester Name">
              <input
                value={profile.ownerName ?? ''}
                onChange={e => upd('ownerName', e.target.value)}
                placeholder="e.g. Jane Smith"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
            </Row>

            <Row label="Owner / Attester Email">
              <input
                type="email"
                value={profile.ownerEmail ?? ''}
                onChange={e => upd('ownerEmail', e.target.value)}
                placeholder="e.g. jane@yourcompany.com"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
              <p className="text-[10px] text-slate-600 mt-1">Used to identify you on attestations you create.</p>
            </Row>
            </>)}

            <Row label="Industry">
              <select
                value={profile.industry}
                onChange={e => upd('industry', e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              >
                <option value="">Select industry…</option>
                {INDUSTRIES.map(i => <option key={i} value={i}>{i}</option>)}
              </select>
            </Row>

            <Row label="Email Provider">
              <div className="grid grid-cols-2 gap-2">
                {EMAIL_PROVIDERS.map(p => (
                  <button key={p} onClick={() => upd('emailProvider', p)}
                    className={`py-2 text-xs rounded-lg border transition-colors ${
                      profile.emailProvider === p
                        ? 'bg-indigo-600 border-indigo-600 text-white'
                        : 'border-slate-700 text-slate-400 hover:border-slate-500'
                    }`}>
                    {p}
                  </button>
                ))}
              </div>
            </Row>

            <Row label="Sensitive Data">
              <div className="space-y-1.5">
                {SENSITIVE_DATA.map(({ id, label, flag }) => {
                  const sel = profile.sensitiveData?.includes(id);
                  return (
                    <button key={id}
                      onClick={() => upd('sensitiveData', sel
                        ? (profile.sensitiveData || []).filter(x => x !== id)
                        : [...(profile.sensitiveData || []), id])}
                      className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm border transition-colors ${
                        sel ? 'bg-indigo-600/20 border-indigo-500 text-white' : 'border-slate-700 text-slate-400 hover:border-slate-600'
                      }`}>
                      <span>{label}</span>
                      {flag && <span className="text-xs bg-amber-500/20 text-amber-400 px-1.5 py-0.5 rounded">{flag}</span>}
                    </button>
                  );
                })}
              </div>
            </Row>

            <div className="px-5 py-4">
              <button onClick={save}
                className={`w-full py-3 rounded-xl text-sm font-semibold transition-colors ${
                  saved ? 'bg-green-600 text-white' : 'bg-indigo-600 hover:bg-indigo-500 text-white'
                }`}>
                {saved ? '✓ Saved' : isApi ? 'Saved automatically' : 'Save Profile'}
              </button>
            </div>
          </fieldset>
        </div>

        {isApi && <TeamSection />}
        {isApi && <AuditSection />}
        {isApi && <AccountSection />}

        {/* Integrations */}
        <div className="mt-6">
          <p className="px-5 text-xs text-slate-500 uppercase tracking-wider mb-2">Integrations</p>
          <div className="bg-slate-900 border-y border-slate-800">
            {[
              { name: 'Microsoft 365', icon: '📧', status: 'coming_soon' },
              { name: 'Google Workspace', icon: '🔵', status: 'coming_soon' },
              { name: 'AWS', icon: '☁️', status: 'coming_soon' },
            ].map(({ name, icon, status }) => (
              <div key={name} className="flex items-center justify-between px-5 py-4 border-b border-slate-800 last:border-0">
                <div className="flex items-center gap-3">
                  <span className="text-lg">{icon}</span>
                  <span className="text-sm text-slate-300">{name}</span>
                </div>
                <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">Coming soon</span>
              </div>
            ))}
            <div className="px-5 py-3">
              <p className="text-xs text-slate-500">
                Integrations automatically verify controls — raising evidence confidence and accuracy of your score.
              </p>
            </div>
          </div>
        </div>

        {/* Data management (demo mode only) */}
        {!isApi && <div className="mt-6">
          <p className="px-5 text-xs text-slate-500 uppercase tracking-wider mb-2">Data</p>
          <div className="bg-slate-900 border-y border-slate-800">
            {[
              { label: 'Reset to demo data', icon: RefreshCw, action: resetDemo, danger: false },
              { label: 'Mark all controls as passing', icon: ShieldCheck, action: markAll, danger: false },
              { label: 'Clear all data & restart', icon: Trash2, action: clearAll, danger: true },
            ].map(({ label, icon: Icon, action, danger }) => (
              <button key={label} onClick={action}
                className={`w-full flex items-center justify-between px-5 py-4 border-b border-slate-800 last:border-0 hover:bg-slate-800/50 transition-colors ${
                  danger ? 'text-red-400' : 'text-slate-300'
                }`}>
                <span className="flex items-center gap-3 text-sm">
                  <Icon size={15} /> {label}
                </span>
                <ChevronRight size={14} className="text-slate-600" />
              </button>
            ))}
          </div>
        </div>}

        {/* About */}
        <div className="px-5 py-6">
          <p className="text-xs text-slate-600">SecurityOS v0.3.0 · 31 controls · NIST CSF 2.0 + AI RMF</p>
          <p className="text-xs text-slate-700 mt-1">Confidence-weighted scoring: automated (100%) · integrated (90%) · attested (70%) · manual (50%) · unknown (0%)</p>
        </div>
      </div>
    </div>
  );
}
