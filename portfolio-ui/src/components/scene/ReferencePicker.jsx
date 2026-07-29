import { useState } from 'react';
import { ImageIcon, X } from 'lucide-react';
import { Popover, PopoverTrigger, PopoverContent } from '../ui/popover';
import { api } from '../../lib/api';

// Visual replacement for a plain <select> of role names: picking a scene's
// primary reference means picking an IMAGE (different clothing per scene),
// so the trigger and the popover grid both show actual thumbnails instead of
// text labels. Popover open state is controlled locally so a tile click can
// select AND close in one action.
export function ReferencePicker({ refs, selectedId, onSelect, ring }) {
  const [open, setOpen] = useState(false);
  const selected = refs.find((r) => r.id === selectedId);
  const selectedThumb = selected ? api.getReferenceFileUrl(selected) : null;

  const labelFor = (ref) => {
    const sameRole = refs.filter((r) => r.role === ref.role);
    return sameRole.length > 1
      ? `${ref.role} (${ref.description?.slice(0, 12) || sameRole.indexOf(ref) + 1})`
      : ref.role;
  };

  const pick = (refId) => {
    onSelect(refId);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          title="Primary for this scene — the source of truth used to generate this asset here (can differ from the entity's overall default, e.g. different clothing per scene)"
          className="flex-1 min-w-0 flex items-center gap-1.5 text-[10px] bg-black/50 border border-white/10 rounded px-1 py-0.5 text-slate-300 hover:bg-black/70 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/30"
        >
          {selectedThumb ? (
            <img src={selectedThumb} alt="" className="w-4 h-4 rounded-sm object-cover shrink-0" />
          ) : (
            <ImageIcon className="w-3 h-3 text-slate-600 shrink-0" />
          )}
          <span className="truncate">{selected ? labelFor(selected) : 'Pick reference'}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-2 bg-slate-900 border-white/10" align="start">
        {refs.length === 0 ? (
          <p className="text-[11px] text-slate-500 p-2">
            No references — use the image buttons to add one.
          </p>
        ) : (
          <div className="grid grid-cols-3 gap-1.5 max-h-64 overflow-y-auto">
            <button
              type="button"
              onClick={() => pick(null)}
              title="No reference"
              className={`aspect-square rounded border flex items-center justify-center transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40 ${
                !selectedId
                  ? `border-transparent ring-2 ${ring} bg-black/60`
                  : 'border-white/10 bg-black/40 hover:bg-black/60'
              }`}
            >
              <X className="w-4 h-4 text-slate-500" />
            </button>
            {refs.map((ref) => {
              const thumb = api.getReferenceFileUrl(ref);
              const isSelected = ref.id === selectedId;
              return (
                <button
                  key={ref.id}
                  type="button"
                  onClick={() => pick(ref.id)}
                  title={labelFor(ref)}
                  className={`group/tile flex flex-col rounded overflow-hidden border transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40 ${
                    isSelected ? `border-transparent ring-2 ${ring}` : 'border-white/10 hover:border-white/30'
                  }`}
                >
                  <div className="aspect-square bg-black/50">
                    {thumb ? (
                      <img src={thumb} alt="" className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <ImageIcon className="w-4 h-4 text-slate-700" />
                      </div>
                    )}
                  </div>
                  <span className="text-[9px] text-slate-400 truncate px-0.5 py-0.5 bg-black/60 group-hover/tile:text-slate-200">
                    {labelFor(ref)}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
