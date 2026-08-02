import { Check, Minus } from 'lucide-react';

// Where this shot sits in the production pipeline. Every state is derived from
// real data, never stored — the stepper is a readout, not a wizard, so the user
// can jump around and it always reflects the truth.
//
// 3D staging is genuinely optional: when a shot has no capture it renders
// "skipped" (dashed, muted, an em-dash rather than a tick) instead of
// "incomplete", so opting out never reads as an unfinished chore.

function StepDot({ state }) {
  if (state === 'done') {
    return (
      <span className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-300 flex items-center justify-center shrink-0">
        <Check className="w-3 h-3" />
      </span>
    );
  }
  if (state === 'skipped') {
    return (
      <span className="w-5 h-5 rounded-full bg-white/5 text-slate-600 flex items-center justify-center shrink-0">
        <Minus className="w-3 h-3" />
      </span>
    );
  }
  if (state === 'active') {
    return (
      <span className="w-5 h-5 rounded-full border-2 border-fuchsia-400 bg-fuchsia-500/10 shrink-0 shadow-[0_0_10px_-2px] shadow-fuchsia-500/60" />
    );
  }
  return <span className="w-5 h-5 rounded-full border border-white/15 shrink-0" />;
}

export function PipelineStepper({ steps }) {
  return (
    <ol className="flex items-center gap-1 overflow-x-auto pb-1" aria-label="Production pipeline">
      {steps.map((step, i) => (
        <li key={step.key} className="flex items-center gap-1 shrink-0">
          <div className="flex items-center gap-2 px-2 py-1">
            <StepDot state={step.state} />
            <span className="leading-tight">
              <span
                className={`block text-[11px] font-medium ${
                  step.state === 'active'
                    ? 'text-fuchsia-200'
                    : step.state === 'done'
                      ? 'text-slate-300'
                      : 'text-slate-500'
                }`}
              >
                {step.label}
              </span>
              {step.optional && (
                <span className="block text-[9px] text-slate-600">
                  {step.state === 'skipped' ? 'skipped · optional' : 'optional'}
                </span>
              )}
            </span>
          </div>
          {i < steps.length - 1 && (
            <span
              aria-hidden
              className={`w-6 h-px shrink-0 ${
                steps[i + 1].optional || step.optional
                  ? 'border-t border-dashed border-white/20'
                  : step.state === 'done'
                    ? 'bg-emerald-500/30'
                    : 'bg-white/10'
              }`}
            />
          )}
        </li>
      ))}
    </ol>
  );
}
