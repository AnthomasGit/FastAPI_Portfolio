import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../../lib/api';
import { colorFor } from './shotOptions';

// Color-coded dropdown for a fixed-vocabulary shot field (size/angle/movement/
// equipment). Renders as a badge-styled <select> so the shot list stays
// scannable at a glance. A value outside the known vocab (hand-typed earlier,
// or an AI draft that didn't match) still shows — neutral color — and is kept
// as its own option so switching away and back doesn't lose it.
export function BadgeSelectCell({ value, field, fieldConfig, shotId, sceneId }) {
  const queryClient = useQueryClient();
  const [saving, setSaving] = useState(false);
  const color = colorFor(fieldConfig, value);
  const options = value && !fieldConfig.options.includes(value)
    ? [value, ...fieldConfig.options]
    : fieldConfig.options;

  const handleChange = async (e) => {
    const next = e.target.value;
    setSaving(true);
    try {
      await api.updateShot(shotId, { [field]: next || null });
      await queryClient.invalidateQueries({ queryKey: ['shots', sceneId] });
    } finally {
      setSaving(false);
    }
  };

  return (
    <select
      value={value || ''}
      onChange={handleChange}
      disabled={saving}
      // No w-full: an unconstrained <select> auto-sizes to its own content
      // (the selected option's text), so the badge is never clipped and the
      // column self-adjusts to whichever option is currently showing —
      // rather than a hardcoded width that truncates longer values.
      className={`text-[11px] font-medium rounded-full px-2 py-0.5 border-0 appearance-none cursor-pointer text-center disabled:opacity-50 transition-colors focus:outline-none focus:ring-1 ${color.bg} ${color.text} ${color.ring}`}
    >
      <option value="" className="bg-slate-900 text-slate-500">—</option>
      {options.map((o) => (
        <option key={o} value={o} className="bg-slate-900 text-slate-200">{o}</option>
      ))}
    </select>
  );
}
