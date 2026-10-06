/**
 * AttestView — Third-party coverage attestation wizard
 *
 * Step 1: Select provider (or custom)
 * Step 2: Review and confirm which controls are covered
 * Step 3: Type ATTEST to confirm
 * Step 4: Success summary
 *
 * Key invariants enforced here:
 *  - User MUST type "ATTEST" exactly — no checkbox substitution
 *  - System NEVER silently converts manual → attested
 *  - Each attestation has explicit control scope — no "attest everything"
 *  - Timestamp comes from the system (Date.now()) not a user entry
 */
import { useState, useMemo } from 'react';
import { useApp } from '../../SecurityOSApp';
import { getControlById, STATUS } from '../../data/controls';
import {
  PROVIDERS, PROVIDERS_BY_CATEGORY, CATEGORY_LABELS,
  PROVIDERS_BY_ID, ATTESTATION_VALIDITY_OPTIONS,
  DEFAULT_VALIDITY_DAYS, CONFIRMATION_PHRASE,
} from '../../data/thirdPartyProviders';
import {
  ArrowLeft, Search, CheckSquare, Square, ShieldCheck,
  Clock, AlertTriangle, ChevronRight, X,
} from 'lucide-react';

// ── Step indicators ───────────────────────────────────────────────────────────
function Steps({ current }) {
  const steps = ['Platform', 'Controls', 'Confirm', 'Done'];
  return (
    <div className="flex items-center px-5 py-3 gap-0">
      {steps.map((label, i) => {
        const idx = i + 1;
        const done = current > idx;
        const active = current === idx;
        return (
          <div key={label} className="flex items-center flex-1 last:flex-none">
            <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
              done ? 'bg-green-500 text-white' : active ? 'bg-indigo-600 text-white' : 'bg-slate-800 text-slate-500'
            }`}>
              {done ? '✓' : idx}
            </div>
            <p className={`text-[10px] ml-1 font-medium truncate ${active ? 'text-white' : done ? 'text-green-400' : 'text-slate-600'}`}>
              {label}
            </p>
            {i < steps.length - 1 && <div className={`h-px flex-1 mx-2 ${done ? 'bg-green-500' : 'bg-slate-800'}`} />}
          </div>
        );
      })}
    </div>
  );
}

// ── Step 1: Provider Selection ────────────────────────────────────────────────
function StepProvider({ preSelectedControls, onSelect, onBack }) {
  const [search, setSearch] = useState('');
  const [customMode, setCustomMode] = useState(false);
  const [customName, setCustomName] = useState('');
  const [customDesc, setCustomDesc] = useState('');

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return PROVIDERS.filter(p =>
      !q ||
      p.name.toLowerCase().includes(q) ||
      p.product?.toLowerCase().includes(q) ||
      p.category.toLowerCase().includes(q)
    );
  }, [search]);

  // Group filtered results by category
  const grouped = useMemo(() => {
    const out = {};
    for (const p of filtered) {
      if (!out[p.category]) out[p.category] = [];
      out[p.category].push(p);
    }
    return out;
  }, [filtered]);

  if (customMode) {
    return (
      <div className="flex flex-col h-full px-5 py-4 space-y-4">
        <button onClick={() => setCustomMode(false)} className="flex items-center gap-2 text-slate-400 text-sm">
          <ArrowLeft size={14} /> Back to catalog
        </button>
        <div>
          <h2 className="text-white font-bold text-base mb-1">Custom Platform</h2>
          <p className="text-slate-400 text-xs">Enter the name of your security platform or process.</p>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-slate-500 block mb-1.5">Platform / Product Name</label>
            <input
              value={customName}
              onChange={e => setCustomName(e.target.value)}
              placeholder="e.g. Cylance, Webroot, Barracuda..."
              className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 block mb-1.5">Coverage Description</label>
            <textarea
              value={customDesc}
              onChange={e => setCustomDesc(e.target.value)}
              rows={3}
              placeholder="Briefly describe what security coverage this platform provides..."
              className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-none"
            />
          </div>
        </div>
        <button
          onClick={() => onSelect({ id: null, name: customName, product: null, description: customDesc, controls: preSelectedControls || [], icon: '🔒' })}
          disabled={!customName.trim()}
          className="w-full py-3.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white text-sm font-semibold transition-colors"
        >
          Continue with {customName || 'Custom Platform'} →
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-5 py-4 space-y-3">
        <div>
          <h2 className="text-white font-bold text-base">Which platform covers this?</h2>
          <p className="text-slate-400 text-xs mt-1">Select the security platform that provides this coverage. You'll confirm the specific controls next.</p>
        </div>
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search CrowdStrike, Okta, Veeam..."
            className="w-full bg-slate-800 border border-slate-700 rounded-xl pl-9 pr-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
          />
          {search && (
            <button onClick={() => setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500">
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-5">
        {Object.entries(grouped).map(([cat, providers]) => (
          <div key={cat}>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium mb-2">
              {CATEGORY_LABELS[cat] || cat}
            </p>
            <div className="space-y-1.5">
              {providers.map(p => (
                <button
                  key={p.id}
                  onClick={() => onSelect(p)}
                  className="w-full flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50 hover:bg-slate-800 hover:border-indigo-500/30 transition-all text-left"
                >
                  <span className="text-2xl shrink-0">{p.icon}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-white">{p.name}</p>
                    {p.product && <p className="text-xs text-slate-400">{p.product}</p>}
                    <p className="text-[10px] text-indigo-400 mt-0.5">{p.controls.length} control{p.controls.length !== 1 ? 's' : ''} covered</p>
                  </div>
                  <ChevronRight size={14} className="text-slate-500 shrink-0" />
                </button>
              ))}
            </div>
          </div>
        ))}

        <button
          onClick={() => setCustomMode(true)}
          className="w-full py-3 rounded-xl border border-dashed border-slate-700 text-slate-500 text-sm hover:border-slate-500 hover:text-slate-300 transition-colors"
        >
          + My platform isn't listed
        </button>
      </div>
    </div>
  );
}

// ── Step 2: Control Coverage Review ──────────────────────────────────────────
function StepControls({ provider, preSelectedControlIds, allControls, onNext, onBack }) {
  const providerControlIds = provider.controls || [];

  // Pre-check provider controls + any explicitly pre-selected failing controls
  const initSelected = new Set([...providerControlIds, ...(preSelectedControlIds || [])]);
  const [selected, setSelected] = useState(initSelected);
  const [description, setDescription] = useState(provider.description || '');
  const [validity, setValidity] = useState(DEFAULT_VALIDITY_DAYS);

  function toggle(controlId) {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(controlId)) next.delete(controlId);
      else next.add(controlId);
      return next;
    });
  }

  // Group controls by category for display
  const grouped = useMemo(() => {
    const out = {};
    for (const c of allControls) {
      if (!out[c.category]) out[c.category] = [];
      out[c.category].push(c);
    }
    return out;
  }, [allControls]);

  const selectedArray = [...selected];

  return (
    <div className="flex flex-col h-full">
      <div className="px-5 py-4 border-b border-slate-800">
        <div className="flex items-center gap-3 mb-3">
          <span className="text-2xl">{provider.icon}</span>
          <div>
            <p className="text-white font-bold text-sm">{provider.name}</p>
            {provider.product && <p className="text-xs text-slate-400">{provider.product}</p>}
          </div>
        </div>
        <p className="text-xs text-slate-400">
          Review the controls this platform covers. Uncheck any that are NOT covered by this platform.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
        {/* Control checklist grouped by category */}
        {Object.entries(grouped).map(([cat, controls]) => (
          <div key={cat}>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium mb-2">{cat.replace('_', ' ')}</p>
            <div className="space-y-1.5">
              {controls.map(c => {
                const isChecked = selected.has(c.id);
                const isProviderCovered = providerControlIds.includes(c.id);
                return (
                  <button
                    key={c.id}
                    onClick={() => toggle(c.id)}
                    className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl border transition-all text-left ${
                      isChecked
                        ? 'bg-indigo-600/10 border-indigo-500/40 text-white'
                        : 'bg-slate-800/40 border-slate-700/40 text-slate-400'
                    }`}
                  >
                    {isChecked
                      ? <CheckSquare size={16} className="text-indigo-400 shrink-0" />
                      : <Square size={16} className="text-slate-600 shrink-0" />
                    }
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">{c.short_name}</p>
                      <p className="text-[10px] text-slate-500 truncate">{c.name}</p>
                    </div>
                    {isProviderCovered && !isChecked && (
                      <span className="text-[10px] text-slate-600 shrink-0">unchecked</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}

        {/* Coverage description */}
        <div>
          <label className="text-xs text-slate-500 block mb-1.5">Coverage Description</label>
          <textarea
            value={description}
            onChange={e => setDescription(e.target.value)}
            rows={3}
            placeholder="Describe what coverage this platform provides..."
            className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-none"
          />
        </div>

        {/* Validity period */}
        <div>
          <label className="text-xs text-slate-500 block mb-2">Attestation Valid For</label>
          <div className="grid grid-cols-2 gap-2">
            {ATTESTATION_VALIDITY_OPTIONS.map(opt => (
              <button
                key={opt.days}
                onClick={() => setValidity(opt.days)}
                className={`py-2.5 text-xs rounded-xl border transition-colors font-medium ${
                  validity === opt.days
                    ? 'bg-indigo-600 border-indigo-600 text-white'
                    : 'border-slate-700 text-slate-400 hover:border-slate-500'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="px-5 py-4 border-t border-slate-800">
        <button
          onClick={() => onNext({ controlIds: selectedArray, description, validity })}
          disabled={selectedArray.length === 0}
          className="w-full py-3.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white text-sm font-semibold transition-colors"
        >
          Review Attestation ({selectedArray.length} control{selectedArray.length !== 1 ? 's' : ''}) →
        </button>
      </div>
    </div>
  );
}

// ── Step 3: ATTEST Confirmation ───────────────────────────────────────────────
function StepConfirm({ provider, controlIds, description, validity, profile, onConfirm, onBack }) {
  const [phrase, setPhrase] = useState('');
  const phraseOk = phrase.trim() === CONFIRMATION_PHRASE;

  const controlNames = controlIds.map(id => {
    const c = getControlById(id);
    return c ? c.short_name : id;
  });

  const expiryDate = new Date(Date.now() + validity * 86400000).toLocaleDateString('en-US', {
    month: 'long', day: 'numeric', year: 'numeric',
  });

  const attesterName = profile?.ownerName || profile?.businessName || 'Account Owner';
  const attesterEmail = profile?.ownerEmail || '';

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5">
        {/* Summary card */}
        <div className="rounded-2xl bg-slate-800/60 border border-slate-700 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-xl">{provider.icon}</span>
            <div>
              <p className="text-white font-bold text-sm">{provider.name}</p>
              {provider.product && <p className="text-xs text-slate-400">{provider.product}</p>}
            </div>
          </div>

          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5">Controls covered</p>
            <div className="flex flex-wrap gap-1.5">
              {controlNames.map(name => (
                <span key={name} className="text-xs px-2 py-0.5 rounded-full bg-indigo-600/20 text-indigo-400 font-medium">
                  {name}
                </span>
              ))}
            </div>
          </div>

          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Coverage Description</p>
            <p className="text-xs text-slate-300 leading-relaxed">{description}</p>
          </div>

          <div className="flex items-center gap-2 pt-1 border-t border-slate-700">
            <Clock size={12} className="text-slate-500 shrink-0" />
            <p className="text-xs text-slate-400">
              Valid for <span className="text-white font-medium">{validity} days</span> — expires {expiryDate}
            </p>
          </div>
        </div>

        {/* Attester identity */}
        <div className="rounded-xl bg-slate-800/40 border border-slate-700/60 px-4 py-3 space-y-1">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider">Attested By</p>
          <p className="text-sm text-white font-semibold">{attesterName}</p>
          {attesterEmail && <p className="text-xs text-slate-400">{attesterEmail}</p>}
          <p className="text-xs text-slate-500 flex items-center gap-1">
            <Clock size={10} /> {new Date().toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })}
          </p>
        </div>

        {/* Legal-weight statement */}
        <div className="rounded-xl bg-amber-500/8 border border-amber-500/20 px-4 py-3">
          <div className="flex items-start gap-2">
            <AlertTriangle size={13} className="text-amber-400 mt-0.5 shrink-0" />
            <p className="text-xs text-amber-200/80 leading-relaxed">
              By typing <span className="font-bold text-amber-400">ATTEST</span> below, I confirm that{' '}
              <span className="font-semibold text-white">{provider.name}</span> currently provides the security
              coverage described above. This attestation will be recorded with a server timestamp and is
              subject to revalidation in {validity} days.
            </p>
          </div>
        </div>

        {/* ATTEST input */}
        <div>
          <label className="text-xs text-slate-400 block mb-2">
            Type <span className="font-bold text-white">ATTEST</span> to confirm:
          </label>
          <input
            value={phrase}
            onChange={e => setPhrase(e.target.value)}
            placeholder="ATTEST"
            autoCapitalize="characters"
            className={`w-full text-center text-lg font-bold tracking-widest py-3.5 rounded-xl border bg-slate-800 focus:outline-none transition-colors ${
              phraseOk
                ? 'border-green-500 text-green-400'
                : phrase.length > 0
                ? 'border-red-500/40 text-red-400'
                : 'border-slate-700 text-white'
            }`}
          />
          {phrase.length > 0 && !phraseOk && (
            <p className="text-xs text-red-400 mt-1 text-center">Type ATTEST exactly (case sensitive)</p>
          )}
        </div>
      </div>

      <div className="px-5 py-4 border-t border-slate-800">
        <button
          onClick={() => onConfirm({ attesterName, attesterEmail })}
          disabled={!phraseOk}
          className="w-full py-3.5 rounded-xl bg-green-600 hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-bold transition-colors"
        >
          {phraseOk ? '✓ Confirm Attestation' : 'Confirm Attestation'}
        </button>
      </div>
    </div>
  );
}

// ── Step 4: Success ───────────────────────────────────────────────────────────
function StepSuccess({ provider, controlIds, validity, attestedAt, onDone }) {
  const controlNames = controlIds.map(id => {
    const c = getControlById(id);
    return c ? c.short_name : id;
  });
  const expiryDate = new Date(Date.now() + validity * 86400000).toLocaleDateString('en-US', {
    month: 'long', day: 'numeric', year: 'numeric',
  });

  return (
    <div className="flex flex-col items-center justify-center h-full px-6 text-center">
      <div className="w-16 h-16 rounded-2xl bg-green-500/15 flex items-center justify-center mb-4">
        <ShieldCheck size={32} className="text-green-400" />
      </div>
      <h2 className="text-white font-bold text-xl mb-2">Attestation Recorded</h2>
      <p className="text-slate-400 text-sm mb-6 leading-relaxed">
        {provider.name} coverage has been attested for {controlIds.length} control{controlIds.length !== 1 ? 's' : ''}.
      </p>

      <div className="w-full rounded-2xl bg-slate-800/60 border border-slate-700 p-4 text-left space-y-3 mb-6">
        <div className="flex flex-wrap gap-1.5">
          {controlNames.map(name => (
            <span key={name} className="text-xs px-2 py-0.5 rounded-full bg-green-500/15 text-green-400 font-medium">
              ✓ {name}
            </span>
          ))}
        </div>
        <div className="flex items-center gap-2 pt-2 border-t border-slate-700">
          <Clock size={12} className="text-slate-500" />
          <p className="text-xs text-slate-400">Expires <span className="text-white font-medium">{expiryDate}</span></p>
        </div>
      </div>

      <div className="w-full rounded-xl bg-indigo-500/8 border border-indigo-500/20 px-4 py-3 text-left mb-6">
        <p className="text-xs text-indigo-300 leading-relaxed">
          These controls now show <span className="font-bold text-white">Attested Third-Party Coverage</span> in your
          Security Readiness Score. Evidence confidence is 70% — connect a direct integration to raise it to 90–100%.
        </p>
      </div>

      <button
        onClick={onDone}
        className="w-full py-3.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold transition-colors"
      >
        Back to Dashboard
      </button>
    </div>
  );
}

// ── Main AttestView ───────────────────────────────────────────────────────────
export default function AttestView({ preSelectedControlIds, onBack }) {
  const { profile, updateStatus, catalog, statuses, addAttestation, mode, me, workflow } = useApp();
  const [submitting, setSubmitting] = useState(false);
  const [step, setStep] = useState(1);
  const [provider, setProvider] = useState(null);
  const [coverage, setCoverage] = useState(null);  // { controlIds, description, validity }
  const [attestedAt, setAttestedAt] = useState(null);

  // All controls from catalog for the coverage step
  const allControls = catalog || [];

  function handleProviderSelect(p) {
    setProvider(p);
    setStep(2);
  }

  function handleCoverageNext(data) {
    setCoverage(data);
    setStep(3);
  }

  async function handleConfirm({ attesterName, attesterEmail }) {
    if (mode === 'api') {
      // Server records who attested (from the sign-in token) and when.
      setSubmitting(true);
      try {
        const r = await workflow.createAttestation({
          source_name: [provider.name, provider.product].filter(Boolean).join(' '),
          source_description: coverage.description || provider.description || `${provider.name} coverage`,
          control_ids: coverage.controlIds,
          confirmation_phrase: 'ATTEST',
          validity_days: coverage.validity,
        });
        setAttestedAt(r?.attestation?.created_at ?? new Date().toISOString());
        setStep(4);
      } catch {
        /* error toast already shown */
      } finally {
        setSubmitting(false);
      }
      return;
    }

    const now = new Date().toISOString();
    setAttestedAt(now);

    // Create attestation record
    const attestation = {
      id: `attest-${Date.now().toString(16)}`,
      providerId: provider.id,
      providerName: provider.name,
      providerProduct: provider.product,
      providerIcon: provider.icon,
      controlIds: coverage.controlIds,
      description: coverage.description,
      validity: coverage.validity,
      attesterName,
      attesterEmail,
      attestedAt: now,
      expiresAt: new Date(Date.now() + coverage.validity * 86400000).toISOString(),
      status: 'active',
    };

    // Register the attestation in app state
    if (addAttestation) addAttestation(attestation);

    // Update each attested control status
    for (const controlId of coverage.controlIds) {
      updateStatus(controlId, STATUS.PASS, `Covered by ${provider.name}`, 'attested_third_party');
    }

    setStep(4);
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 pt-12 pb-3 border-b border-slate-800">
        <button
          onClick={step === 1 ? onBack : () => setStep(s => s - 1)}
          className="w-9 h-9 rounded-xl bg-slate-800 flex items-center justify-center text-slate-400 hover:text-white shrink-0"
        >
          <ArrowLeft size={18} />
        </button>
        <div>
          <h1 className="text-white font-bold text-sm">Third-Party Attestation</h1>
          <p className="text-xs text-slate-500">Confirm third-party security coverage</p>
        </div>
      </div>

      {/* Step indicator */}
      <Steps current={step} />

      {/* Step content */}
      <div className="flex-1 overflow-y-auto">
        {step === 1 && (
          <StepProvider
            preSelectedControls={preSelectedControlIds}
            onSelect={handleProviderSelect}
            onBack={onBack}
          />
        )}
        {step === 2 && provider && (
          <StepControls
            provider={provider}
            preSelectedControlIds={preSelectedControlIds}
            allControls={allControls}
            onNext={handleCoverageNext}
            onBack={() => setStep(1)}
          />
        )}
        {step === 3 && provider && coverage && (
          <StepConfirm
            provider={provider}
            controlIds={coverage.controlIds}
            description={coverage.description}
            validity={coverage.validity}
            profile={mode === 'api' ? { ownerName: me?.display_name, ownerEmail: me?.email } : profile}
            onConfirm={submitting ? () => {} : handleConfirm}
            onBack={() => setStep(2)}
          />
        )}
        {step === 4 && (
          <StepSuccess
            provider={provider}
            controlIds={coverage.controlIds}
            validity={coverage.validity}
            attestedAt={attestedAt}
            onDone={onBack}
          />
        )}
      </div>
    </div>
  );
}
