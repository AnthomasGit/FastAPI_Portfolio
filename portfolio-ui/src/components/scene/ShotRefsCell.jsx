import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Images, ChevronUp, ChevronDown, RotateCcw } from 'lucide-react';
import { Popover, PopoverTrigger, PopoverContent } from '../ui/popover';
import { api } from '../../lib/api';

// Which assets fill this shot's reference slots, and in what ORDER.
//
// Order is load-bearing, not cosmetic: reference N becomes image{N} in the
// graph and <Subject N> in the composed H3 prompt. Reordering here changes
// which picture the prompt's "Subject 2" actually describes.
//
// clip_refs === null means "use the scene default" (characters by name, then
// locations, then props). The first edit materialises that default into an
// explicit list; "Reset to default" writes null again.
const MAX_SLOTS = 9;

const ACCENT = {
  character: 'text-cast',
  location: 'text-set',
  prop: 'text-prop',
};

// The scene's linked entities in the same order the backend computes by
// default, so an un-overridden shot shows exactly what it will render with.
function sceneDefaultRefs(scene) {
  const byName = (a, b) => (a.name || '').localeCompare(b.name || '');
  const withThumb = (items, links, type) =>
    [...(items || [])].sort(byName).map((e) => {
      const link = (links || []).find((l) => l.entity_id === e.id);
      return { entity_type: type, entity_id: e.id, name: e.name, url: link?.reference_url || null };
    });
  return [
    ...withThumb(scene.characters, scene.character_links, 'character'),
    ...withThumb(scene.locations, scene.location_links, 'location'),
    ...withThumb(scene.props, scene.prop_links, 'prop'),
  ];
}

export function ShotRefsCell({ shot, sceneId, scene }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  const available = sceneDefaultRefs(scene);
  const isDefault = shot.clip_refs == null;
  // Resolve the stored override against the scene, dropping entries whose
  // entity is no longer linked (clip_refs has no FK, so pins can dangle).
  const current = isDefault
    ? available
    : (shot.clip_refs || [])
        .map((r) => available.find(
          (a) => a.entity_type === r.entity_type && a.entity_id === r.entity_id))
        .filter(Boolean);

  const save = useMutation({
    mutationFn: (refs) => api.updateShot(shot.id, {
      clip_refs: refs === null ? null : refs.map(({ entity_type, entity_id }) => ({ entity_type, entity_id })),
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shots', sceneId] }),
  });

  const toggle = (item) => {
    const on = current.some((c) => c.entity_id === item.entity_id);
    save.mutate(on
      ? current.filter((c) => c.entity_id !== item.entity_id)
      : [...current, item]);
  };

  const move = (idx, delta) => {
    const next = [...current];
    const to = idx + delta;
    if (to < 0 || to >= next.length) return;
    [next[idx], next[to]] = [next[to], next[idx]];
    save.mutate(next);
  };

  const over = current.length > MAX_SLOTS;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          title="Which assets fill this shot's reference slots, and in what order (slot N = Subject N in the prompt)"
          className="flex items-center gap-1 text-[10px] bg-bay-900 border border-line rounded px-1.5 py-0.5 text-fg hover:bg-bay-950/80 transition-colors"
        >
          <Images className="w-3 h-3 text-fg-faint shrink-0" />
          <span className={over ? 'text-lead-400' : ''}>{current.length}/{MAX_SLOTS}</span>
          {isDefault && <span className="text-fg-faint">default</span>}
        </button>
      </PopoverTrigger>

      <PopoverContent className="w-72 p-2 bg-bay-850 border-line" align="start">
        <div className="flex items-center justify-between mb-1.5">
          <span className="label-slug">Reference slots</span>
          {!isDefault && (
            <button
              type="button"
              onClick={() => save.mutate(null)}
              title="Follow the scene default again"
              className="flex items-center gap-1 text-[10px] text-fg-faint hover:text-fg transition-colors"
            >
              <RotateCcw className="w-3 h-3" /> Reset
            </button>
          )}
        </div>

        {over && (
          <p className="mb-1.5 text-[10px] text-lead-400">
            Only the first {MAX_SLOTS} are used — the rest are dropped at render.
          </p>
        )}

        <ul className="space-y-1 max-h-56 overflow-y-auto">
          {available.map((item) => {
            const idx = current.findIndex((c) => c.entity_id === item.entity_id);
            const on = idx >= 0;
            return (
              <li key={`${item.entity_type}:${item.entity_id}`}
                  className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => toggle(item)}
                  className="accent-lead-500 shrink-0"
                />
                <span className={`w-4 text-[10px] font-mono shrink-0 ${on && idx < MAX_SLOTS ? 'text-fg' : 'text-fg-faint'}`}>
                  {on ? idx + 1 : '·'}
                </span>
                <span className="w-7 h-7 rounded border border-line bg-bay-900 overflow-hidden shrink-0">
                  {item.url
                    ? <img src={api.getReferenceFileUrl({ url: item.url })} alt="" className="w-full h-full object-cover" />
                    : null}
                </span>
                <span className={`flex-1 truncate text-[11px] ${ACCENT[item.entity_type]}`}>
                  {item.name}
                </span>
                {on && (
                  <span className="flex flex-col shrink-0">
                    <button type="button" onClick={() => move(idx, -1)} disabled={idx === 0}
                      title="Move up a slot"
                      className="text-fg-faint hover:text-fg disabled:opacity-25 leading-none">
                      <ChevronUp className="w-3 h-3" />
                    </button>
                    <button type="button" onClick={() => move(idx, 1)} disabled={idx === current.length - 1}
                      title="Move down a slot"
                      className="text-fg-faint hover:text-fg disabled:opacity-25 leading-none">
                      <ChevronDown className="w-3 h-3" />
                    </button>
                  </span>
                )}
              </li>
            );
          })}
          {available.length === 0 && (
            <li className="text-[11px] text-fg-faint px-1 py-2">
              No assets linked to this scene yet.
            </li>
          )}
        </ul>

        <p className="mt-1.5 pt-1.5 border-t border-line text-[10px] text-fg-faint leading-snug">
          Slot order is the prompt's <span className="font-mono">Subject</span> numbering —
          reorder to change which image “Subject 2” describes.
        </p>
      </PopoverContent>
    </Popover>
  );
}
