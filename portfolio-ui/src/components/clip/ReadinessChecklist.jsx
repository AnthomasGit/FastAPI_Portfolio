import { Check, Circle, AlertCircle } from 'lucide-react';

// "N of M ready" with the detail one click away. The point is that a disabled
// Generate button must never be a dead end — the list always names exactly what
// is missing and whether it actually blocks.

export function ReadinessChecklist({ items }) {
  const met = items.filter((i) => i.met).length;
  const blocking = items.filter((i) => i.required && !i.met);
  const ready = blocking.length === 0;

  return (
    <details className="group rounded-lg border border-white/10 bg-black/30">
      <summary className="flex items-center gap-2 px-3 py-2 cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden">
        <span
          className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
            ready ? 'bg-emerald-500/15 text-emerald-300' : 'bg-amber-500/15 text-amber-300'
          }`}
        >
          {met} of {items.length} ready
        </span>
        <span className="text-[11px] text-slate-400 flex-1 truncate">
          {ready ? 'All requirements met' : `Missing: ${blocking.map((b) => b.label).join(', ')}`}
        </span>
        <span className="text-[10px] text-slate-600 group-open:hidden">details</span>
      </summary>
      <ul className="px-3 pb-2 space-y-1">
        {items.map((item) => (
          <li key={item.key} className="flex items-center gap-2 text-[11px]">
            {item.met ? (
              <Check className="w-3 h-3 text-emerald-400 shrink-0" />
            ) : item.required ? (
              <AlertCircle className="w-3 h-3 text-amber-400 shrink-0" />
            ) : (
              <Circle className="w-3 h-3 text-slate-600 shrink-0" />
            )}
            <span className={item.met ? 'text-slate-300' : 'text-slate-500'}>{item.label}</span>
            {!item.required && !item.met && (
              <span className="text-[9px] text-slate-600">optional</span>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}
