import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { api } from '../../lib/api';
import { ShotStillCell } from './ShotStillCell';
import { BadgeSelectCell } from './BadgeSelectCell';
import { SHOT_SIZE, ANGLE, MOVEMENT, EQUIPMENT } from './shotOptions';

// One editable cell that commits on blur. Kept uncontrolled-ish via local state
// so typing doesn't round-trip per keystroke. Re-syncs to a changed server
// value during render (React's recommended alternative to a setState effect).
function EditCell({ value, field, shotId, sceneId, placeholder, wide }) {
  const queryClient = useQueryClient();
  const [val, setVal] = useState(value ?? '');
  const [lastValue, setLastValue] = useState(value);
  if (value !== lastValue) {
    setLastValue(value);
    setVal(value ?? '');
  }

  const save = () => {
    if ((val ?? '') === (value ?? '')) return;
    api.updateShot(shotId, { [field]: val }).then(() =>
      queryClient.invalidateQueries({ queryKey: ['shots', sceneId] })
    );
  };

  return (
    <input
      value={val}
      placeholder={placeholder}
      onChange={(e) => setVal(e.target.value)}
      onBlur={save}
      onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur(); }}
      className={`bg-transparent text-xs text-slate-200 px-1 py-1 rounded focus:outline-none focus:bg-black/40 focus:ring-1 focus:ring-cyan-500/40 placeholder:text-slate-700 ${wide ? 'w-full min-w-[180px]' : 'w-full'}`}
    />
  );
}

export function ShotRow({ shot, sceneId, availableStills }) {
  const queryClient = useQueryClient();
  const delMut = useMutation({
    mutationFn: () => api.deleteShot(shot.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shots', sceneId] }),
  });

  const cell = (field, placeholder, wide) => (
    <EditCell value={shot[field]} field={field} shotId={shot.id} sceneId={sceneId} placeholder={placeholder} wide={wide} />
  );

  return (
    <tr className="border-b border-white/5 hover:bg-white/[0.02] align-top">
      <td className="px-2 py-2 w-16">{cell('shot_number', '1A')}</td>
      <td className="px-2 py-2 whitespace-nowrap">
        <BadgeSelectCell value={shot.shot_size} field="shot_size" fieldConfig={SHOT_SIZE} shotId={shot.id} sceneId={sceneId} />
      </td>
      <td className="px-2 py-2 whitespace-nowrap">
        <BadgeSelectCell value={shot.angle} field="angle" fieldConfig={ANGLE} shotId={shot.id} sceneId={sceneId} />
      </td>
      <td className="px-2 py-2 whitespace-nowrap">
        <BadgeSelectCell value={shot.movement} field="movement" fieldConfig={MOVEMENT} shotId={shot.id} sceneId={sceneId} />
      </td>
      <td className="px-2 py-2 min-w-[200px]">{cell('description', 'What the shot shows…', true)}</td>
      <td className="px-2 py-2 whitespace-nowrap">
        <BadgeSelectCell value={shot.equipment} field="equipment" fieldConfig={EQUIPMENT} shotId={shot.id} sceneId={sceneId} />
      </td>
      <td className="px-2 py-2 min-w-[160px]">{cell('audio_notes', 'Audio / notes…', true)}</td>
      <td className="px-2 py-2 w-44">
        <ShotStillCell shot={shot} sceneId={sceneId} availableStills={availableStills} />
      </td>
      <td className="px-2 py-2 w-8">
        <button
          onClick={() => delMut.mutate()}
          disabled={delMut.isPending}
          title="Delete shot"
          className="p-1 rounded text-slate-600 hover:text-red-400 hover:bg-red-500/10 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-red-400"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </td>
    </tr>
  );
}
