import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { api } from '../../lib/api';
import { ShotStillCell } from './ShotStillCell';
import { BadgeSelectCell } from './BadgeSelectCell';
import { SHOT_SIZE, ANGLE, MOVEMENT, EQUIPMENT } from './shotOptions';
import { shotReadiness } from './shotReadiness';

// One editable cell that commits on blur. Kept uncontrolled-ish via local state
// so typing doesn't round-trip per keystroke. Re-syncs to a changed server
// value during render (React's recommended alternative to a setState effect).
function EditCell({ value, field, shotId, sceneId, placeholder, wide, mono }) {
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
      className={`bg-transparent text-xs text-fg px-1 py-1 rounded-frame focus:outline-none focus:bg-bay-900 placeholder:text-fg-faint ${
        mono ? 'font-mono font-bold uppercase' : ''
      } ${wide ? 'w-full min-w-[180px]' : 'w-full'}`}
    />
  );
}

export function ShotRow({ shot, sceneId, availableStills }) {
  const queryClient = useQueryClient();
  const delMut = useMutation({
    mutationFn: () => api.deleteShot(shot.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shots', sceneId] }),
  });

  const cell = (field, placeholder, wide, mono) => (
    <EditCell value={shot[field]} field={field} shotId={shot.id} sceneId={sceneId} placeholder={placeholder} wide={wide} mono={mono} />
  );

  return (
    <tr className="group border-b border-line hover:bg-bay-800 align-top transition-colors">
      {/* Shot codes (1A, 1B…) are the one identifier the crew calls out loud —
          set in the data face so they hold the eye down the column. */}
      <td className="px-2 py-2 w-16">{cell('shot_number', '1A', false, true)}</td>
      <td className="px-2 py-2 whitespace-nowrap">
        {(() => {
          const r = shotReadiness(shot);
          return (
            <span
              className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${r.cls}`}
              title={
                r.blocking.length
                  ? `Missing: ${r.blocking.map((b) => b.label).join(', ')}`
                  : `${r.met} of ${r.total} details filled in`
              }
            >
              {r.label}
            </span>
          );
        })()}
      </td>
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
          className="p-1 rounded text-fg-faint hover:text-stop hover:bg-stop/15 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-stop"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </td>
    </tr>
  );
}
