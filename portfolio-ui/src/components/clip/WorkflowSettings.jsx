// Renders a workflow's tunable knobs generically from its registry spec
// (GET /api/video-workflows `settings`), so a new workflow's settings panel
// needs no frontend changes — just a spec on the backend.
//
// A spec becomes: a <select> when it has `options` (a fixed COMBO on the
// ComfyUI node — anything else fails validation there), a slider when it has
// `step`, otherwise a bounded number input.
export function WorkflowSettings({ specs, values, onChange }) {
  if (!specs.length) return null;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 px-3 pb-3">
      {specs.map((spec) => (
        <div key={spec.id} className={spec.step != null ? 'col-span-2' : undefined}>
          <label className="block">
            <span className="block text-[9px] text-slate-500 mb-0.5">{spec.label}</span>
            {spec.options ? (
              <select
                value={values[spec.id]}
                onChange={(e) => onChange(spec.id, Number(e.target.value))}
                className="w-full text-[11px] bg-black/40 border border-white/10 rounded px-2 py-1 text-slate-200 focus:outline-none focus:ring-1 focus:ring-fuchsia-400"
              >
                {spec.options.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            ) : spec.step != null ? (
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min={spec.min}
                  max={spec.max}
                  step={spec.step}
                  value={values[spec.id]}
                  onChange={(e) => onChange(spec.id, Number(e.target.value))}
                  className="flex-1 accent-fuchsia-500"
                />
                <span className="text-[10px] text-slate-400 w-9 text-right shrink-0">
                  {values[spec.id]}
                </span>
              </div>
            ) : (
              <input
                type="number"
                min={spec.min}
                max={spec.max}
                value={values[spec.id]}
                onChange={(e) => onChange(spec.id, Number(e.target.value))}
                className="w-full text-[11px] bg-black/40 border border-white/10 rounded px-2 py-1 text-slate-200 focus:outline-none focus:ring-1 focus:ring-fuchsia-400"
              />
            )}
          </label>
          {spec.help && <p className="text-[9px] text-slate-600 mt-1 leading-snug">{spec.help}</p>}
        </div>
      ))}
    </div>
  );
}
