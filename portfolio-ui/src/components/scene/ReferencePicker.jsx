import { useState } from 'react';
import { ChevronDown, ImageIcon, X } from 'lucide-react';
import { Popover, PopoverTrigger, PopoverContent } from '../ui/popover';
import { api } from '../../lib/api';

// Visual replacement for a plain <select> of role names: picking a scene's
// primary reference means picking an IMAGE (different clothing per scene),
// so the popover grid shows actual thumbnails instead of text labels. The
// trigger itself stays text-only — the card's own thumbnail above it already
// shows the current picture, so a second copy in the trigger is redundant.
// Popover open state is controlled locally so a tile click can select AND
// close in one action.
export function ReferencePicker({ refs, selectedId, onSelect, ring }) {
  const [open, setOpen] = useState(false);
  const selected = refs.find((r) => r.id === selectedId);

  // The backend derives `label` (slot → prompt excerpt → upload+date) so every
  // consumer names a reference the same way and the client needs no extra fetch
  // of asset images. Role is the last resort: it is "moodboard" for essentially
  // every generated image, which is what made this picker unreadable.
  const labelFor = (ref) => ref.label || ref.description || ref.role;

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
          className="flex-1 min-w-0 flex items-center gap-1.5 text-[10px] bg-bay-900 border border-line rounded px-1 py-0.5 text-fg hover:bg-bay-950/80 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bay-600"
        >
          <span className="truncate flex-1">{selected ? labelFor(selected) : 'Pick reference'}</span>
          <ChevronDown className="w-3 h-3 text-fg-faint shrink-0" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-2 bg-bay-850 border-line" align="start">
        {refs.length === 0 ? (
          <p className="text-[11px] text-fg-muted p-2">
            No references — use the image buttons to add one.
          </p>
        ) : (
          <div className="grid grid-cols-3 gap-1.5 max-h-64 overflow-y-auto">
            <button
              type="button"
              onClick={() => pick(null)}
              title="No reference"
              className={`aspect-square rounded border flex items-center justify-center transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bay-600 ${
                !selectedId
                  ? `border-transparent ring-2 ${ring} bg-bay-900`
                  : 'border-line bg-bay-900 hover:bg-bay-900'
              }`}
            >
              <X className="w-4 h-4 text-fg-muted" />
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
                  className={`group/tile flex flex-col rounded overflow-hidden border transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bay-600 ${
                    isSelected ? `border-transparent ring-2 ${ring}` : 'border-line hover:border-bay-600'
                  }`}
                >
                  <div className="aspect-square bg-bay-900">
                    {thumb ? (
                      <img src={thumb} alt="" className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <ImageIcon className="w-4 h-4 text-fg-faint" />
                      </div>
                    )}
                  </div>
                  <span className="text-[9px] text-fg-muted truncate px-0.5 py-0.5 bg-bay-900 group-hover/tile:text-fg">
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
