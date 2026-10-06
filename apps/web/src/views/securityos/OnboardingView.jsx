import { useState } from 'react';
import { ShieldCheck, ChevronRight, ChevronLeft, Check } from 'lucide-react';

const INDUSTRIES = [
  'Medical / Dental Practice',
  'Mental Health / Therapy',
  'Legal Services / Law Firm',
  'Accounting / CPA',
  'Financial Advisory',
  'Insurance Agency',
  'Real Estate',
  'Consulting',
  'Marketing / Creative Agency',
  'IT / MSP',
  'E-commerce',
  'Construction / Contracting',
  'Other Professional Services',
];

const EMPLOYEE_RANGES = ['Just me', '2–5', '6–10', '11–25', '26–50', '50+'];

const CLOUD_PROVIDERS = [
  'Microsoft 365 / Azure',
  'Google Workspace',
  'AWS',
  'Dropbox',
  'Salesforce',
  'QuickBooks Online',
  'Other / None',
];

const SENSITIVE_DATA = [
  { id: 'phi', label: 'Health / Medical Records (PHI)', flag: 'HIPAA' },
  { id: 'pii', label: 'Customer Personal Info (PII)', flag: null },
  { id: 'payment', label: 'Payment Card Data', flag: 'PCI DSS' },
  { id: 'financial', label: 'Financial Records', flag: null },
  { id: 'legal', label: 'Confidential Legal Documents', flag: null },
  { id: 'federal', label: 'Federal / Government Data', flag: 'CMMC' },
  { id: 'children', label: "Children's Data", flag: 'COPPA' },
];

const EMAIL_PROVIDERS = [
  'Microsoft 365 (Outlook)',
  'Google Workspace (Gmail)',
  'Other hosted email',
  'On-premise mail server',
];

const STEPS = [
  { id: 'welcome', title: 'Welcome' },
  { id: 'business', title: 'Your Business' },
  { id: 'cloud', title: 'Your Tools' },
  { id: 'data', title: 'Your Data' },
  { id: 'done', title: 'All Set' },
];

function MultiSelect({ options, selected, onChange, getLabel, getKey }) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((opt) => {
        const key = getKey ? getKey(opt) : opt;
        const label = getLabel ? getLabel(opt) : opt;
        const isSelected = selected.includes(key);
        return (
          <button
            key={key}
            type="button"
            onClick={() =>
              onChange(
                isSelected ? selected.filter((s) => s !== key) : [...selected, key]
              )
            }
            className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-all ${
              isSelected
                ? 'bg-indigo-600 border-indigo-600 text-white'
                : 'border-slate-700 text-slate-300 hover:border-slate-500'
            }`}
          >
            {isSelected && <Check size={12} className="inline mr-1" />}
            {label}
          </button>
        );
      })}
    </div>
  );
}

export default function OnboardingView({ profile, setProfile, onComplete, skipLabel = 'Skip setup (use demo data)' }) {
  const [step, setStep] = useState(0);

  function update(key, value) {
    setProfile((p) => ({ ...p, [key]: value }));
  }

  const canAdvance = () => {
    if (step === 1) return profile.businessName.trim() && profile.industry && profile.employeeCount;
    if (step === 2) return profile.emailProvider;
    return true;
  };

  function next() {
    if (step < STEPS.length - 1) setStep(step + 1);
    else onComplete();
  }

  function back() {
    if (step > 0) setStep(step - 1);
  }

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-lg">
        {/* Logo */}
        <div className="flex items-center justify-center gap-2 mb-8">
          <div className="w-10 h-10 rounded-xl bg-indigo-600 flex items-center justify-center">
            <ShieldCheck size={20} className="text-white" />
          </div>
          <span className="font-bold text-2xl tracking-tight text-white">SecurityOS</span>
        </div>

        {/* Progress */}
        {step > 0 && step < STEPS.length - 1 && (
          <div className="mb-6">
            <div className="flex justify-between text-xs text-slate-500 mb-1.5">
              <span>{STEPS[step].title}</span>
              <span>Step {step} of {STEPS.length - 2}</span>
            </div>
            <div className="h-1 bg-slate-800 rounded-full">
              <div
                className="h-full bg-indigo-600 rounded-full transition-all duration-300"
                style={{ width: `${((step - 1) / (STEPS.length - 2)) * 100}%` }}
              />
            </div>
          </div>
        )}

        {/* Card */}
        <div className="bg-slate-900 rounded-2xl border border-slate-800 p-8">
          {/* Step 0: Welcome */}
          {step === 0 && (
            <div className="text-center">
              <div className="text-5xl mb-4">🛡️</div>
              <h1 className="text-2xl font-bold text-white mb-3">
                Security that works for your business
              </h1>
              <p className="text-slate-400 mb-6 leading-relaxed">
                SecurityOS continuously monitors your security posture, tells you exactly what needs
                fixing, and builds the evidence you need to prove you&apos;re protected — without the
                compliance jargon.
              </p>
              <div className="grid grid-cols-3 gap-4 mb-8 text-center">
                {[
                  { emoji: '🎯', label: 'Clear score' },
                  { emoji: '🔧', label: 'Guided fixes' },
                  { emoji: '🏅', label: 'Trust Passport' },
                ].map((item) => (
                  <div key={item.label} className="bg-slate-800 rounded-xl p-3">
                    <div className="text-2xl mb-1">{item.emoji}</div>
                    <div className="text-xs text-slate-400">{item.label}</div>
                  </div>
                ))}
              </div>
              <button
                onClick={next}
                className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 rounded-xl font-semibold text-white transition-colors"
              >
                Get Started
              </button>
            </div>
          )}

          {/* Step 1: Business info */}
          {step === 1 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-bold text-white mb-1">Tell us about your business</h2>
                <p className="text-slate-400 text-sm">We use this to tailor your security profile.</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5">
                  Business Name
                </label>
                <input
                  type="text"
                  value={profile.businessName}
                  onChange={(e) => update('businessName', e.target.value)}
                  placeholder="e.g. Smith & Associates"
                  className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5">Industry</label>
                <select
                  value={profile.industry}
                  onChange={(e) => update('industry', e.target.value)}
                  className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-indigo-500"
                >
                  <option value="">Select your industry…</option>
                  {INDUSTRIES.map((i) => <option key={i} value={i}>{i}</option>)}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  Number of Employees
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {EMPLOYEE_RANGES.map((r) => (
                    <button
                      key={r}
                      type="button"
                      onClick={() => update('employeeCount', r)}
                      className={`py-2 rounded-lg text-sm font-medium border transition-all ${
                        profile.employeeCount === r
                          ? 'bg-indigo-600 border-indigo-600 text-white'
                          : 'border-slate-700 text-slate-300 hover:border-slate-500'
                      }`}
                    >
                      {r}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Step 2: Cloud tools */}
          {step === 2 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-bold text-white mb-1">What tools do you use?</h2>
                <p className="text-slate-400 text-sm">This helps us check the right places for security issues.</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Email Provider</label>
                <div className="space-y-2">
                  {EMAIL_PROVIDERS.map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => update('emailProvider', p)}
                      className={`w-full text-left px-4 py-2.5 rounded-lg text-sm border transition-all ${
                        profile.emailProvider === p
                          ? 'bg-indigo-600/20 border-indigo-500 text-white'
                          : 'border-slate-700 text-slate-300 hover:border-slate-500'
                      }`}
                    >
                      {profile.emailProvider === p && <Check size={14} className="inline mr-2 text-indigo-400" />}
                      {p}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  Cloud Platforms <span className="text-slate-500 font-normal">(select all that apply)</span>
                </label>
                <MultiSelect
                  options={CLOUD_PROVIDERS}
                  selected={profile.cloudProviders}
                  onChange={(v) => update('cloudProviders', v)}
                />
              </div>
            </div>
          )}

          {/* Step 3: Data */}
          {step === 3 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-bold text-white mb-1">What data do you handle?</h2>
                <p className="text-slate-400 text-sm">
                  Different data types have different protection requirements.
                </p>
              </div>

              <div className="space-y-2">
                {SENSITIVE_DATA.map((item) => {
                  const selected = profile.sensitiveData.includes(item.id);
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() =>
                        update(
                          'sensitiveData',
                          selected
                            ? profile.sensitiveData.filter((s) => s !== item.id)
                            : [...profile.sensitiveData, item.id]
                        )
                      }
                      className={`w-full text-left px-4 py-2.5 rounded-lg text-sm border transition-all flex items-center justify-between ${
                        selected
                          ? 'bg-indigo-600/20 border-indigo-500 text-white'
                          : 'border-slate-700 text-slate-300 hover:border-slate-500'
                      }`}
                    >
                      <span className="flex items-center gap-2">
                        {selected && <Check size={14} className="text-indigo-400 shrink-0" />}
                        {item.label}
                      </span>
                      {item.flag && (
                        <span className="text-xs bg-amber-500/20 text-amber-400 px-2 py-0.5 rounded font-medium">
                          {item.flag}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>

              <p className="text-xs text-slate-500">
                Don&apos;t see your data type? You can update this later in Settings.
              </p>
            </div>
          )}

          {/* Step 4: Done */}
          {step === 4 && (
            <div className="text-center">
              <div className="text-5xl mb-4">🚀</div>
              <h2 className="text-2xl font-bold text-white mb-3">You&apos;re all set!</h2>
              <p className="text-slate-400 mb-6 leading-relaxed">
                We&apos;ve built your initial security profile for <strong className="text-white">{profile.businessName || 'your business'}</strong>.
                Your dashboard is ready — here&apos;s what to expect.
              </p>
              <div className="bg-slate-800 rounded-xl p-4 text-left space-y-3 mb-6">
                {[
                  { emoji: '📊', text: 'Your Security Readiness Score' },
                  { emoji: '🔴', text: 'Issues that need attention' },
                  { emoji: '🔧', text: 'Step-by-step fix guides' },
                  { emoji: '🤖', text: 'AI Copilot for any questions' },
                  { emoji: '🏅', text: 'Trust Passport to share with clients' },
                ].map((item) => (
                  <div key={item.text} className="flex items-center gap-3 text-sm text-slate-300">
                    <span className="text-lg">{item.emoji}</span>
                    {item.text}
                  </div>
                ))}
              </div>
              <button
                onClick={onComplete}
                className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 rounded-xl font-semibold text-white transition-colors"
              >
                Go to My Dashboard →
              </button>
            </div>
          )}

          {/* Nav buttons */}
          {step > 0 && step < STEPS.length - 1 && (
            <div className="flex gap-3 mt-6">
              <button
                onClick={back}
                className="flex items-center gap-1 px-4 py-2.5 rounded-xl text-sm font-medium text-slate-400 hover:text-white border border-slate-700 hover:border-slate-500 transition-colors"
              >
                <ChevronLeft size={16} /> Back
              </button>
              <button
                onClick={next}
                disabled={!canAdvance()}
                className={`flex-1 flex items-center justify-center gap-1 py-2.5 rounded-xl text-sm font-semibold transition-colors ${
                  canAdvance()
                    ? 'bg-indigo-600 hover:bg-indigo-500 text-white'
                    : 'bg-slate-800 text-slate-500 cursor-not-allowed'
                }`}
              >
                {step === STEPS.length - 2 ? 'Finish Setup' : 'Continue'} <ChevronRight size={16} />
              </button>
            </div>
          )}
        </div>

        {step === 0 && (
          <button
            onClick={() => { setProfile((p) => ({ ...p, businessName: 'My Business', industry: 'Consulting', employeeCount: '2–5', emailProvider: 'Microsoft 365 (Outlook)', cloudProviders: ['Microsoft 365 / Azure'], sensitiveData: [] })); onComplete(); }}
            className="mt-4 w-full text-center text-slate-500 text-sm hover:text-slate-400"
          >
            {skipLabel}
          </button>
        )}
      </div>
    </div>
  );
}
