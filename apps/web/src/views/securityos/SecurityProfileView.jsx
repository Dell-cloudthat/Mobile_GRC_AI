/**
 * SecurityProfileView — Executive Security Profile
 *
 * Level 1 view: answers "How secure is this organization right now?"
 * Intentionally clean and executive-friendly.
 * Links directly to FixRoadmapView (operational) and ReportView (technical).
 */
import { useApp, ScoreRing } from '../../SecurityOSApp';
import AwaitingYou from '../../api/AwaitingYou';
import { calculateFrameworkReadiness, toGrade } from '../../data/scoring';
import { calculateTCO, riskLevel, fmtUSD } from '../../data/risk';
import {
  Shield, AlertTriangle, Target, FileText, Share2, Clock,
  Zap, ShieldCheck, PenLine, TrendingDown, ChevronRight,
  CheckCircle2, XCircle, Activity,
} from 'lucide-react';

const SCORE_COLOR = {
  green:  { text: 'text-green-400',  bg: 'bg-green-500/10',  border: 'border-green-500/30',  bar: 'bg-green-500'  },
  blue:   { text: 'text-indigo-400', bg: 'bg-indigo-500/10', border: 'border-indigo-500/30', bar: 'bg-indigo-500' },
  yellow: { text: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', bar: 'bg-yellow-500' },
  orange: { text: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/30', bar: 'bg-orange-500' },
  red:    { text: 'text-red-400',    bg: 'bg-red-500/10',    border: 'border-red-500/30',    bar: 'bg-red-500'    },
};

function MetricCard({ label, value, color = 'text-white', subLabel, bg = 'bg-slate-800/60' }) {
  return (
    <div className={`${bg} rounded-xl p-3`}>
      <p className="text-[10px] text-slate-500 mb-0.5">{label}</p>
      <p className={`text-xl font-bold tabular-nums ${color}`}>{value}</p>
      {subLabel && <p className="text-[10px] text-slate-600 mt-0.5">{subLabel}</p>}
    </div>
  );
}

export default function SecurityProfileView() {
  const {
    scoring, profile, statuses, catalog,
    openRisk, openReport, setView, attestations,
  } = useApp();

  const { totalScore, color, issues, passing, evidenceBreakdown, allControls, summary } = scoring;
  const grade = toGrade(totalScore);

  const c = SCORE_COLOR[color] || SCORE_COLOR.blue;

  // Evidence breakdown
  const { automated = 0, integrated = 0, attested = 0, manual = 0 } = evidenceBreakdown;
  const passCount = passing.length;
  const autoCount = automated + integrated;

  // Issue severity counts
  const critFail  = issues.filter(x => x.severity === 'critical' && x.status === 'fail').length;
  const highFail  = issues.filter(x => x.severity === 'high'     && x.status === 'fail').length;
  const openTotal = issues.length;

  // Verification coverage
  const verifiedPct = scoring.verifiedPct;

  // Framework readiness
  const fwReadiness = calculateFrameworkReadiness(allControls);

  // TCO / risk
  const tco = calculateTCO(profile, statuses, issues, catalog);
  const rl  = riskLevel(tco);
  const RISK_COLOR = {
    red:    { text: 'text-red-400',    bg: 'bg-red-500/10',    border: 'border-red-500/25'    },
    orange: { text: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/25' },
    yellow: { text: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/25' },
    green:  { text: 'text-green-400',  bg: 'bg-green-500/8',   border: 'border-green-500/20'  },
  };
  const rc = RISK_COLOR[rl.color] || RISK_COLOR.yellow;

  // Expiring attestations (≤14 days)
  const expiringCount = attestations.filter(a => {
    if (a.status !== 'active') return false;
    const days = Math.floor((new Date(a.expiresAt) - Date.now()) / 86400000);
    return days >= 0 && days <= 14;
  }).length;

  const today = new Date().toLocaleDateString('en-US', {
    year: 'numeric', month: 'long', day: 'numeric',
  });

  function handleShare() {
    const text = `${profile.businessName || 'Our business'} — Security Readiness: ${totalScore}/100 (${grade}) — Verified by SecurityOS on ${today}.`;
    navigator.clipboard.writeText(text).catch(() => {});
  }

  return (
    <div className="flex flex-col min-h-full">
      {/* Header */}
      <div className="px-5 pt-12 pb-4 border-b border-slate-800">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-widest font-medium">SecurityOS Security Profile</p>
            <h1 className="text-white font-bold text-xl mt-0.5">
              {profile.businessName || 'Your Business'}
            </h1>
            {profile.industry && (
              <p className="text-slate-400 text-xs mt-0.5">{profile.industry}</p>
            )}
          </div>
          <button
            onClick={handleShare}
            className="w-9 h-9 rounded-xl bg-slate-800 flex items-center justify-center text-slate-400 hover:text-white transition-colors shrink-0"
            title="Copy summary"
          >
            <Share2 size={16} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">

        {/* Score + grade */}
        <div className="px-5 pt-5 pb-4">
          <div className="flex items-center gap-4">
            <div className="relative shrink-0">
              <ScoreRing score={totalScore} size={108} strokeWidth={8} />
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-3xl font-bold text-white tabular-nums">{totalScore}</span>
                <span className="text-[10px] text-slate-500">/ 100</span>
              </div>
            </div>
            <div className="flex-1 min-w-0 space-y-2">
              <div className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-bold ${c.bg} ${c.text}`}>
                <Shield size={12} /> {grade}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <MetricCard
                  label="Critical Risks"
                  value={critFail}
                  color={critFail > 0 ? 'text-red-400' : 'text-green-400'}
                  bg="bg-slate-800/60"
                />
                <MetricCard
                  label="Open Fixes"
                  value={openTotal}
                  color={openTotal > 0 ? 'text-yellow-400' : 'text-green-400'}
                  bg="bg-slate-800/60"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Key metrics row */}
        <div className="px-5 pb-4 grid grid-cols-3 gap-2">
          <MetricCard label="Passing" value={summary.passing} color="text-green-400" />
          <MetricCard label="Verified" value={`${verifiedPct}%`} color="text-indigo-400" />
          <MetricCard label="High Risk" value={highFail} color={highFail > 0 ? 'text-orange-400' : 'text-green-400'} />
        </div>

        {/* Work waiting on this person (connected mode) */}
        <AwaitingYou />

        {/* Alerts */}
        {expiringCount > 0 && (
          <div className="mx-5 mb-3 px-4 py-3 rounded-xl bg-amber-500/10 border border-amber-500/25 flex items-center gap-2.5">
            <AlertTriangle size={13} className="text-amber-400 shrink-0" />
            <p className="text-xs text-amber-300 flex-1">
              {expiringCount} attestation{expiringCount > 1 ? 's' : ''} expiring within 14 days
            </p>
            <button
              onClick={() => setView('roadmap')}
              className="text-[10px] text-amber-400 font-semibold shrink-0"
            >
              Review →
            </button>
          </div>
        )}

        {/* Primary actions */}
        <div className="px-5 pb-4 grid grid-cols-2 gap-2">
          <button
            onClick={() => setView('roadmap')}
            className="flex items-center justify-center gap-2 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold transition-colors"
          >
            <Target size={14} /> Fix Roadmap
          </button>
          <button
            onClick={openReport}
            className="flex items-center justify-center gap-2 py-3 rounded-xl bg-slate-800 border border-slate-700 text-slate-300 text-sm font-medium hover:bg-slate-700 transition-colors"
          >
            <FileText size={14} /> Full Report
          </button>
        </div>

        {/* Evidence sources */}
        <div className="mx-5 mb-4 rounded-2xl bg-slate-800/40 border border-slate-700/50 p-4">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium mb-3">Evidence Sources</p>
          {passCount === 0 ? (
            <p className="text-xs text-slate-600 text-center py-2">No passing controls yet</p>
          ) : (
            <div className="space-y-2.5">
              {[
                { label: 'Automated', count: autoCount,  icon: Zap,        col: 'text-green-400',  bar: 'bg-green-500'  },
                { label: 'Attested',  count: attested,   icon: ShieldCheck, col: 'text-indigo-400', bar: 'bg-indigo-500' },
                { label: 'Manual',    count: manual,     icon: PenLine,    col: 'text-slate-400',  bar: 'bg-slate-500'  },
              ].map(({ label, count, icon: Icon, col, bar }) => {
                const pct = passCount > 0 ? Math.round((count / passCount) * 100) : 0;
                return (
                  <div key={label}>
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-1.5">
                        <Icon size={11} className={col} />
                        <span className={`text-xs font-medium ${col}`}>{label}</span>
                      </div>
                      <span className="text-xs text-slate-500">{count} ({pct}%)</span>
                    </div>
                    <div className="h-1.5 bg-slate-700/60 rounded-full">
                      <div className={`h-full rounded-full ${bar} transition-all`} style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Framework readiness */}
        {fwReadiness.length > 0 && (
          <div className="mx-5 mb-4 rounded-2xl bg-slate-800/40 border border-slate-700/50 p-4">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium mb-3">Framework Readiness</p>
            <div className="space-y-2.5">
              {fwReadiness.slice(0, 5).map(fw => (
                <div key={fw.id}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-slate-300">{fw.label}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-slate-500">{fw.passing}/{fw.total}</span>
                      <span className={`text-xs font-bold ${
                        fw.pct >= 80 ? 'text-green-400' : fw.pct >= 60 ? 'text-yellow-400' : 'text-red-400'
                      }`}>{fw.pct}%</span>
                    </div>
                  </div>
                  <div className="h-1.5 bg-slate-700/60 rounded-full">
                    <div
                      className={`h-full rounded-full transition-all ${
                        fw.pct >= 80 ? 'bg-green-500' : fw.pct >= 60 ? 'bg-yellow-500' : 'bg-red-500'
                      }`}
                      style={{ width: `${fw.pct}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Financial risk teaser */}
        <div className="mx-5 mb-4">
          <button
            onClick={openRisk}
            className={`w-full rounded-2xl ${rc.bg} ${rc.border} border p-4 text-left hover:opacity-90 transition-opacity`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <TrendingDown size={13} className={rc.text} />
                <span className={`text-[10px] font-semibold uppercase tracking-wider ${rc.text}`}>
                  Financial Risk
                </span>
              </div>
              <ChevronRight size={13} className="text-slate-600" />
            </div>
            <p className={`text-2xl font-bold tabular-nums ${rc.text}`}>
              {fmtUSD(tco.annual_risk_cost)}
            </p>
            <p className="text-xs text-slate-500 mt-0.5">Estimated annual risk exposure · View full analysis</p>
          </button>
        </div>

        {/* Footer meta */}
        <div className="px-5 pb-6">
          <div className="flex items-center gap-1.5 text-xs text-slate-600">
            <Activity size={11} />
            <span>Profile generated {today} · SecurityOS</span>
          </div>
        </div>
      </div>
    </div>
  );
}
