import { ImageIcon, X } from 'lucide-react';
import { sceneCandidates } from './referenceCandidates';

// Subject + background pickers for reference-driven workflows.
//
// Slot ORDER is load-bearing: the Nth selected subject is wired to the Nth
// LoadImage and described as "Image N:" in the global prompt, so selection is
// an ordered list, not a set, and tiles show their slot number.

const TYPE_STYLE = {
  character: { ring: 'ring-cast/50', text: 'text-cast', label: 'Character' },
  prop: { ring: 'ring-prop/50', text: 'text-prop', label: 'Prop' },
  location: { ring: 'ring-set/50', text: 'text-set', label: 'Location' },
};

function Tile({ candidate, slot, onClick, disabled }) {
  const style = TYPE_STYLE[candidate.type];
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={Boolean(slot)}
      title={`${style.label}: ${candidate.name}`}
      className={`relative group/tile flex flex-col rounded overflow-hidden border transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bay-600 disabled:opacity-30 disabled:cursor-not-allowed ${
        slot ? `border-transparent ring-2 ${style.ring}` : 'border-line hover:border-bay-600'
      }`}
    >
      <div className="aspect-square bg-bay-900">
        {candidate.thumb ? (
          <img src={candidate.thumb} alt="" className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <ImageIcon className="w-4 h-4 text-fg-faint" />
          </div>
        )}
      </div>
      {slot && (
        <span className="absolute top-1 left-1 w-4 h-4 rounded-full bg-bay-950/85 text-[9px] font-semibold text-fg flex items-center justify-center">
          {slot}
        </span>
      )}
      <span className={`text-[9px] truncate px-1 py-0.5 bg-bay-950/80 ${style.text}`}>
        {candidate.name}
      </span>
    </button>
  );
}

export function ReferenceSlots({
  scene, maxRefs, allowBackground,
  selectedKeys, onToggleSubject,
  backgroundKey, onSelectBackground,
}) {
  const { subjects, locations } = sceneCandidates(scene);
  const atCapacity = selectedKeys.length >= maxRefs;

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-baseline justify-between mb-1.5">
          <h3 className="text-[10px] font-semibold text-fg-muted uppercase tracking-wider">
            Subjects
          </h3>
          <span className="text-[10px] text-fg-muted">
            {selectedKeys.length} / {maxRefs} slots
          </span>
        </div>
        {subjects.length === 0 ? (
          <p className="text-[11px] text-fg-muted">
            No characters or props with a chosen reference are linked to this scene. Pick their
            per-scene reference on the Scene Detail page first.
          </p>
        ) : (
          <div className="grid grid-cols-4 sm:grid-cols-6 gap-1.5">
            {subjects.map((c) => {
              const slot = selectedKeys.indexOf(c.key) + 1;
              return (
                <Tile
                  key={c.key}
                  candidate={c}
                  slot={slot || null}
                  disabled={!slot && atCapacity}
                  onClick={() => onToggleSubject(c.key)}
                />
              );
            })}
          </div>
        )}
      </div>

      {allowBackground && (
        <div>
          <h3 className="text-[10px] font-semibold text-fg-muted uppercase tracking-wider mb-1.5">
            Background plate
          </h3>
          {locations.length === 0 ? (
            <p className="text-[11px] text-fg-muted">
              No location with a chosen reference is linked to this scene.
            </p>
          ) : (
            <div className="grid grid-cols-4 sm:grid-cols-6 gap-1.5">
              <button
                type="button"
                onClick={() => onSelectBackground(null)}
                aria-pressed={!backgroundKey}
                title="No background"
                className={`aspect-square rounded border flex items-center justify-center transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bay-600 ${
                  !backgroundKey
                    ? 'border-transparent ring-2 ring-bay-600 bg-bay-900'
                    : 'border-line bg-bay-900 hover:bg-bay-900'
                }`}
              >
                <X className="w-4 h-4 text-fg-muted" />
              </button>
              {locations.map((c) => (
                <Tile
                  key={c.key}
                  candidate={c}
                  slot={backgroundKey === c.key ? '·' : null}
                  onClick={() => onSelectBackground(backgroundKey === c.key ? null : c.key)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
