import { useEffect } from 'react';
import { Trophy, X } from 'lucide-react';

// Small, dismissible, auto-expiring. No confetti: a one-off acknowledgement
// that stays out of the way is the version professionals tolerate.
export function MilestoneToast({ milestone, onDismiss }) {
  useEffect(() => {
    if (!milestone) return undefined;
    const t = setTimeout(onDismiss, 6000);
    return () => clearTimeout(t);
  }, [milestone, onDismiss]);

  if (!milestone) return null;

  return (
    <div
      role="status"
      className="fixed bottom-4 right-4 z-50 w-72 rounded-lg border border-emerald-500/30 bg-slate-900 shadow-lg p-3 flex items-start gap-2.5"
    >
      <span className="w-7 h-7 rounded-full bg-emerald-500/15 text-emerald-300 flex items-center justify-center shrink-0">
        <Trophy className="w-3.5 h-3.5" />
      </span>
      <span className="flex-1 min-w-0">
        <span className="block text-xs font-semibold text-slate-100">{milestone.title}</span>
        <span className="block text-[11px] text-slate-400 mt-0.5">{milestone.body}</span>
      </span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="text-slate-600 hover:text-slate-300 transition-colors shrink-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/30 rounded"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
