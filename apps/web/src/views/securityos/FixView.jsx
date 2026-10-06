import { useState, useRef, useEffect } from 'react';
import RemediationActions from '../../api/RemediationActions';
import { useApp } from '../../SecurityOSApp';
import { getControlById, STATUS, SEVERITY_COLOR, CATEGORY_LABEL } from '../../data/controls';
import { respondForControl, SUGGESTED_BY_CATEGORY } from '../../data/copilot';
import {
  ArrowLeft, CheckCheck, RotateCcw, Clock, ShieldAlert,
  Bot, Send, Sparkles, ChevronDown, ChevronUp,
  Monitor, Users, Zap, ShieldCheck,
} from 'lucide-react';

const SEVERITY_LABEL = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' };

// ── Identity integration stub ─────────────────────────────────────────────
function IdentityIntegrationStub({ control, profile }) {
  const [expanded, setExpanded] = useState(false);
  const isIdentityRelated = ['identity', 'organization'].includes(control?.category);
  if (!isIdentityRelated) return null;

  const provider = profile?.emailProvider || '';
  const isMicrosoft = provider.toLowerCase().includes('microsoft') || provider.toLowerCase().includes('365');
  const isGoogle = provider.toLowerCase().includes('google');
  const providerLabel = isMicrosoft ? 'Microsoft 365' : isGoogle ? 'Google Workspace' : 'your email provider';

  const mockUsers = [
    { name: 'Alex Johnson', email: 'alex@example.com', mfaStatus: 'enrolled', risk: 'low' },
    { name: 'Sam Rivera',   email: 'sam@example.com',  mfaStatus: 'missing',  risk: 'high' },
    { name: 'Jordan Lee',   email: 'jordan@example.com', mfaStatus: 'missing', risk: 'high' },
  ];

  return (
    <div className="rounded-2xl border border-slate-700/50 overflow-hidden">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-4 py-3 bg-slate-800/60 hover:bg-slate-800 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Users size={15} className="text-indigo-400 shrink-0" />
          <span className="text-sm font-semibold text-white">Affected Users</span>
          <span className="text-xs px-1.5 py-0.5 rounded-full bg-slate-700 text-slate-400">Preview</span>
        </div>
        {expanded ? <ChevronUp size={15} className="text-slate-500" /> : <ChevronDown size={15} className="text-slate-500" />}
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-2 space-y-3 bg-slate-900/50">
          {/* Connect prompt */}
          <div className="flex items-start gap-2 p-3 rounded-xl bg-indigo-600/10 border border-indigo-500/20">
            <Zap size={13} className="text-indigo-400 mt-0.5 shrink-0" />
            <p className="text-xs text-indigo-300 leading-relaxed">
              Connect {providerLabel} to automatically pull live user status and send targeted remediation emails.
            </p>
          </div>

          {/* Sample user list */}
          <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Sample — connect integration to see live data</p>
          <div className="space-y-2">
            {mockUsers.map(u => (
              <div key={u.email} className="flex items-center gap-3 py-2 border-b border-slate-800/60 last:border-0">
                <div className="w-7 h-7 rounded-full bg-slate-700 flex items-center justify-center text-xs font-semibold text-slate-300 shrink-0">
                  {u.name.charAt(0)}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-white font-medium truncate">{u.name}</p>
                  <p className="text-xs text-slate-500 truncate">{u.email}</p>
                </div>
                <span className={`text-xs font-semibold px-2 py-0.5 rounded-full shrink-0 ${
                  u.risk === 'high'
                    ? 'bg-red-500/15 text-red-400'
                    : 'bg-green-500/15 text-green-400'
                }`}>
                  {u.mfaStatus === 'enrolled' ? '✓ Enrolled' : '✗ Missing'}
                </span>
              </div>
            ))}
          </div>

          {/* Desktop recommended banner */}
          <div className="flex items-center gap-2 p-3 rounded-xl bg-slate-800 border border-slate-700">
            <Monitor size={14} className="text-yellow-400 shrink-0" />
            <p className="text-xs text-slate-300 leading-relaxed">
              <span className="font-semibold text-yellow-400">Desktop recommended</span> for bulk user configuration, policy deployment, and integration setup.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Inline Copilot ────────────────────────────────────────────────────────
function InlineCopilot({ control, profile, scoring, onOpenFullCopilot }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  const suggestions = SUGGESTED_BY_CATEGORY[control?.category] || [
    `How do I fix ${control?.short_name}?`,
    `What's the risk of not addressing this?`,
    `How long does this fix take?`,
  ];

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, open]);

  async function ask(text) {
    const q = text || input.trim();
    if (!q) return;
    setInput('');
    setOpen(true);
    setMessages(prev => [...prev, { role: 'user', content: q }]);
    setLoading(true);
    await new Promise(r => setTimeout(r, 400 + Math.random() * 500));
    const answer = respondForControl(q, control, profile, scoring);
    setMessages(prev => [...prev, { role: 'assistant', content: answer }]);
    setLoading(false);
  }

  return (
    <div className="rounded-2xl border border-indigo-500/20 bg-slate-900/60 overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-800/40 transition-colors"
      >
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-xl bg-indigo-600/20 flex items-center justify-center">
            <Bot size={14} className="text-indigo-400" />
          </div>
          <div className="text-left">
            <p className="text-sm font-semibold text-white">Ask Copilot</p>
            <p className="text-[10px] text-indigo-400/70">AI remediation assistant</p>
          </div>
        </div>
        {open
          ? <ChevronUp size={15} className="text-slate-500" />
          : <ChevronDown size={15} className="text-slate-500" />
        }
      </button>

      {open && (
        <div className="border-t border-slate-800/60">
          {/* Suggested question pills */}
          {messages.length === 0 && (
            <div className="px-4 py-3 space-y-2">
              <p className="text-[10px] text-slate-500 flex items-center gap-1 uppercase tracking-wider">
                <Sparkles size={9} /> Suggested questions
              </p>
              <div className="flex flex-wrap gap-1.5">
                {suggestions.map(q => (
                  <button
                    key={q}
                    onClick={() => ask(q)}
                    className="text-xs px-2.5 py-1.5 rounded-full border border-indigo-500/30 text-indigo-400 bg-indigo-600/5 hover:bg-indigo-600/20 transition-colors text-left"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Message thread */}
          {messages.length > 0 && (
            <div className="px-4 py-3 space-y-3 max-h-72 overflow-y-auto">
              {messages.map((m, i) => (
                <div key={i} className={`flex gap-2 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
                  <div className={`w-6 h-6 rounded-full shrink-0 flex items-center justify-center ${
                    m.role === 'user' ? 'bg-indigo-600' : 'bg-slate-700'
                  }`}>
                    {m.role === 'user'
                      ? <span className="text-[9px] font-bold text-white">YOU</span>
                      : <Bot size={11} className="text-indigo-400" />
                    }
                  </div>
                  <div className={`max-w-[85%] text-xs leading-relaxed rounded-2xl px-3 py-2 ${
                    m.role === 'user'
                      ? 'bg-indigo-600 text-white rounded-tr-sm'
                      : 'bg-slate-800 text-slate-200 rounded-tl-sm'
                  }`}>
                    {m.content.split('\n').map((line, j) => {
                      const bold = line.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
                      return <p key={j} className={line === '' ? 'h-1.5' : ''} dangerouslySetInnerHTML={{ __html: bold }} />;
                    })}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="flex gap-2">
                  <div className="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center">
                    <Bot size={11} className="text-indigo-400" />
                  </div>
                  <div className="bg-slate-800 rounded-xl px-3 py-2 flex gap-1 items-center">
                    {[0, 150, 300].map(d => (
                      <span key={d} className="w-1 h-1 rounded-full bg-slate-500 animate-bounce" style={{ animationDelay: `${d}ms` }} />
                    ))}
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          )}

          {/* Input row */}
          <div className="px-3 pb-3 pt-2 flex gap-2 border-t border-slate-800/60">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); } }}
              placeholder="Ask a specific question…"
              className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition-colors"
            />
            <button
              onClick={() => ask()}
              disabled={!input.trim() || loading}
              className="w-8 h-8 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 flex items-center justify-center shrink-0 transition-colors"
            >
              <Send size={12} />
            </button>
          </div>

          {/* Open full Copilot link */}
          <button
            onClick={() => onOpenFullCopilot(`Tell me everything about fixing "${control?.name}" — give me a detailed step-by-step remediation plan.`)}
            className="w-full px-4 py-2.5 flex items-center justify-center gap-1.5 text-xs text-indigo-400/70 hover:text-indigo-400 border-t border-slate-800/60 transition-colors"
          >
            <Bot size={11} />
            Open in full Copilot for deeper guidance →
          </button>
        </div>
      )}
    </div>
  );
}

// ── Main FixView ──────────────────────────────────────────────────────────
export default function FixView({ controlId, onBack }) {
  const { statuses, updateStatus, profile, scoring, openCopilotWithPrompt, openAttest, mode } = useApp();
  const control = getControlById(controlId);

  if (!control) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen px-6">
        <p className="text-slate-400">Control not found.</p>
        <button onClick={onBack} className="mt-4 text-indigo-400 text-sm">← Back</button>
      </div>
    );
  }

  const entry = statuses[controlId] ?? {};
  const currentStatus = entry.status ?? STATUS.UNKNOWN;
  const sevColors = SEVERITY_COLOR[control.severity] || SEVERITY_COLOR.medium;
  const isPassing = currentStatus === STATUS.PASS;
  const categoryLabel = CATEGORY_LABEL[control.category] || control.category;

  return (
    <div className="flex flex-col min-h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 pt-12 pb-4 border-b border-slate-800">
        <button
          onClick={onBack}
          className="w-9 h-9 rounded-xl bg-slate-800 flex items-center justify-center text-slate-400 hover:text-white shrink-0"
        >
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1 min-w-0">
          <p className="text-xs text-slate-500 uppercase tracking-wider">{categoryLabel}</p>
          <h1 className="text-white font-bold text-base truncate">{control.name}</h1>
        </div>
        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full shrink-0 ${sevColors.bg} ${sevColors.text}`}>
          {SEVERITY_LABEL[control.severity]}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5">
        {/* Current status */}
        <div className={`flex items-center gap-3 p-3 rounded-xl border ${
          isPassing
            ? 'bg-green-500/10 border-green-500/30'
            : currentStatus === STATUS.FAIL
            ? `${sevColors.bg} ${sevColors.border}`
            : 'bg-slate-800 border-slate-700'
        }`}>
          <ShieldAlert size={18} className={
            isPassing ? 'text-green-400' :
            currentStatus === STATUS.FAIL ? sevColors.text :
            'text-slate-400'
          } />
          <div>
            <p className={`text-sm font-semibold ${
              isPassing ? 'text-green-400' :
              currentStatus === STATUS.FAIL ? sevColors.text :
              'text-slate-300'
            }`}>
              {isPassing ? 'Currently passing' :
               currentStatus === STATUS.FAIL ? 'Currently failing' :
               currentStatus === STATUS.IN_PROGRESS ? 'Fix in progress' :
               'Status not verified'}
            </p>
            {entry.notes && <p className="text-xs text-slate-400 mt-0.5">{entry.notes}</p>}
          </div>
        </div>

        {/* Why it matters */}
        <div>
          <h2 className="text-xs text-slate-500 uppercase tracking-wider font-medium mb-2">Why it matters</h2>
          <p className="text-slate-300 text-sm leading-relaxed">{control.customer_impact}</p>
        </div>

        {/* How to fix */}
        {!isPassing && (
          <div>
            <h2 className="text-xs text-slate-500 uppercase tracking-wider font-medium mb-3">How to fix it</h2>
            <ol className="space-y-3">
              {(control.remediation_steps || []).map((step, i) => (
                <li key={i} className="flex gap-3">
                  <span className="shrink-0 w-5 h-5 rounded-full bg-indigo-600/30 text-indigo-400 flex items-center justify-center text-xs font-bold mt-0.5">
                    {i + 1}
                  </span>
                  <p className="text-sm text-slate-300 leading-relaxed">{step}</p>
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* Details for passing controls */}
        {isPassing && (
          <div>
            <h2 className="text-xs text-slate-500 uppercase tracking-wider font-medium mb-2">What this covers</h2>
            <p className="text-slate-300 text-sm leading-relaxed">{control.description}</p>
          </div>
        )}

        {/* Copilot inline assist — shown for all non-passing controls */}
        {!isPassing && (
          <InlineCopilot
            control={control}
            profile={profile}
            scoring={scoring}
            onOpenFullCopilot={openCopilotWithPrompt}
          />
        )}

        {/* Identity integration stub */}
        <IdentityIntegrationStub control={control} profile={profile} />

        {/* Evidence & time */}
        <div className="flex items-center gap-4 text-xs text-slate-500 pt-1">
          <span className="flex items-center gap-1">
            <Clock size={11} /> ~{control.estimated_minutes} min to fix
          </span>
          <span className="text-slate-700">·</span>
          <span>{control.id}</span>
        </div>

        {/* Framework tags */}
        {control.framework_mappings && (
          <div>
            <p className="text-xs text-slate-600 mb-2">Framework mappings</p>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(control.framework_mappings).map(([fw, refs]) => (
                <span key={fw} className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-500" title={refs.join(', ')}>
                  {fw.replace(/_/g, ' ').toUpperCase()}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Action buttons */}
      {mode === 'api' ? (
        <div className="sticky bottom-0 z-10 px-5 pb-6 pt-3 border-t border-slate-800 bg-slate-950/95 backdrop-blur">
          <RemediationActions control={control} onBack={onBack} />
        </div>
      ) : (
      <div className="px-5 pb-6 pt-3 border-t border-slate-800 space-y-2">
        {!isPassing && (
          <>
            <button
              onClick={() => { updateStatus(controlId, STATUS.PASS); onBack(); }}
              className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl bg-green-600 hover:bg-green-500 text-white text-sm font-semibold transition-colors"
            >
              <CheckCheck size={17} /> Mark as Fixed
            </button>

            {/* Attestation path — for controls covered by a third-party platform */}
            <button
              onClick={() => openAttest(controlId)}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-slate-800 border border-indigo-500/30 text-indigo-400 text-sm font-medium hover:bg-slate-700 hover:border-indigo-500/60 transition-colors"
            >
              <ShieldCheck size={15} /> Covered by another platform?
            </button>

            {currentStatus !== STATUS.IN_PROGRESS && (
              <button
                onClick={() => { updateStatus(controlId, STATUS.IN_PROGRESS); onBack(); }}
                className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-slate-800 border border-slate-700 text-yellow-400 text-sm font-medium hover:bg-slate-700 transition-colors"
              >
                <RotateCcw size={15} /> Working on it
              </button>
            )}
          </>
        )}
        {isPassing && (
          <button
            onClick={() => { updateStatus(controlId, STATUS.FAIL); onBack(); }}
            className="w-full py-3 rounded-xl bg-slate-800 border border-slate-700 text-slate-400 text-sm font-medium hover:bg-slate-700 transition-colors"
          >
            Mark as Issue
          </button>
        )}
        <button
          onClick={onBack}
          className="w-full py-3 text-slate-500 text-sm hover:text-slate-400 transition-colors"
        >
          Back to dashboard
        </button>
      </div>
      )}
    </div>
  );
}
