import { Check, Clock, Sparkles } from 'lucide-react';

// Cards rather than a dropdown: the workflows differ along several axes at
// once (how many references, whether a still is needed, dialogue support,
// runtime), and a card grid lets those be compared at a glance instead of
// remembered one option at a time.
//
// Capability text is derived from the backend registry, so adding a workflow
// server-side surfaces here with no frontend change.

function capabilities(wf) {
  const caps = [];
  if (wf.needs_still) caps.push('needs a still');
  if (wf.max_refs) caps.push(`${wf.max_refs} references`);
  if (wf.background) caps.push('background plate');
  if (wf.dual_prompt) caps.push('dialogue');
  if (wf.driving_video) caps.push('driving video');
  return caps;
}

function formatEta(seconds) {
  if (!seconds) return null;
  return seconds >= 60 ? `~${Math.round(seconds / 60)} min` : `~${seconds}s`;
}

export function WorkflowCards({ workflows, selected, onSelect, disabledReason }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {workflows.map((wf) => {
        const isSelected = wf.id === selected;
        const blocked = disabledReason?.(wf);
        return (
          <button
            key={wf.id}
            type="button"
            onClick={() => !blocked && onSelect(wf.id)}
            disabled={Boolean(blocked)}
            aria-pressed={isSelected}
            title={blocked || undefined}
            className={`text-left rounded-lg border p-3 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-fuchsia-400 disabled:opacity-40 disabled:cursor-not-allowed ${
              isSelected
                ? 'border-transparent ring-2 ring-fuchsia-500/50 bg-fuchsia-500/10'
                : 'border-white/10 bg-black/40 hover:border-white/25'
            }`}
          >
            <div className="flex items-start gap-2">
              <span className="flex-1 min-w-0">
                <span className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-xs font-semibold text-slate-100">{wf.label}</span>
                  {wf.recommended && (
                    <span className="inline-flex items-center gap-0.5 text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300">
                      <Sparkles className="w-2.5 h-2.5" />
                      Recommended
                    </span>
                  )}
                </span>
                <span className="block text-[10px] text-slate-400 mt-1 leading-snug">
                  {wf.blurb}
                </span>
              </span>
              {isSelected && <Check className="w-4 h-4 text-fuchsia-300 shrink-0" />}
            </div>

            <div className="flex items-center gap-1 flex-wrap mt-2">
              {capabilities(wf).map((c) => (
                <span
                  key={c}
                  className="text-[9px] px-1.5 py-0.5 rounded-full bg-white/5 text-slate-400"
                >
                  {c}
                </span>
              ))}
              {formatEta(wf.est_seconds) && (
                <span className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded-full bg-white/5 text-slate-400">
                  <Clock className="w-2.5 h-2.5" />
                  {formatEta(wf.est_seconds)}
                </span>
              )}
            </div>

            {blocked && (
              <p className="text-[9px] text-amber-400/80 mt-1.5">{blocked}</p>
            )}
          </button>
        );
      })}
    </div>
  );
}
