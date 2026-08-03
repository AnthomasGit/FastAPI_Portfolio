import { ImageIcon, X } from 'lucide-react';
import { sceneCandidates } from './referenceCandidates';

// Optional single-image picker for MiniMax H3 I2V's last-frame keyframe. Draws
// from the same scene reference candidates (characters/props/locations with a
// chosen per-scene reference) as the subject picker, but selects exactly one
// (or none). The still supplies the first frame; this is what the clip
// interpolates toward.
const TYPE_STYLE = {
  character: { ring: 'ring-cast/50', text: 'text-cast' },
  prop: { ring: 'ring-prop/50', text: 'text-prop' },
  location: { ring: 'ring-set/50', text: 'text-set' },
};

// `stillOption` (optional): { key, thumb, label } renders a leading tile for
// the shot's beauty-pass still (the default first frame). `allowNone`: show the
// "none" tile (last frame is optional; first frame is required so pass false).
export function KeyframePicker({
  scene, selectedKey, onSelect, stillOption = null, allowNone = true, noneTitle = 'None',
}) {
  const { subjects, locations } = sceneCandidates(scene);
  const candidates = [...subjects, ...locations];

  if (candidates.length === 0 && !stillOption) {
    return (
      <p className="text-[11px] text-fg-muted">
        No still and no characters, props or locations with a chosen reference are linked to this
        scene — attach a beauty-pass still or pick a reference on the Scene Detail page first.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-4 sm:grid-cols-6 gap-1.5">
      {allowNone && (
        <button
          type="button"
          onClick={() => onSelect(null)}
          aria-pressed={!selectedKey}
          title={noneTitle}
          className={`aspect-square rounded border flex items-center justify-center transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bay-600 ${
            !selectedKey ? 'border-transparent ring-2 ring-bay-600 bg-bay-900' : 'border-line bg-bay-900 hover:bg-bay-900'
          }`}
        >
          <X className="w-4 h-4 text-fg-muted" />
        </button>
      )}
      {stillOption && (
        <button
          type="button"
          onClick={() => onSelect(stillOption.key)}
          aria-pressed={selectedKey === stillOption.key}
          title={stillOption.label || 'Still'}
          className={`relative flex flex-col rounded overflow-hidden border transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bay-600 ${
            selectedKey === stillOption.key ? 'border-transparent ring-2 ring-clip/50' : 'border-line hover:border-bay-600'
          }`}
        >
          <div className="aspect-square bg-bay-900">
            {stillOption.thumb ? (
              <img src={stillOption.thumb} alt="" className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full flex items-center justify-center">
                <ImageIcon className="w-4 h-4 text-fg-faint" />
              </div>
            )}
          </div>
          <span className="text-[9px] truncate px-1 py-0.5 bg-bay-950/80 text-clip">
            {stillOption.label || 'Still'}
          </span>
        </button>
      )}
      {candidates.map((c) => {
        const isSelected = selectedKey === c.key;
        const style = TYPE_STYLE[c.type];
        return (
          <button
            key={c.key}
            type="button"
            onClick={() => onSelect(isSelected ? null : c.key)}
            aria-pressed={isSelected}
            title={c.name}
            className={`relative flex flex-col rounded overflow-hidden border transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bay-600 ${
              isSelected ? `border-transparent ring-2 ${style.ring}` : 'border-line hover:border-bay-600'
            }`}
          >
            <div className="aspect-square bg-bay-900">
              {c.thumb ? (
                <img src={c.thumb} alt="" className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <ImageIcon className="w-4 h-4 text-fg-faint" />
                </div>
              )}
            </div>
            <span className={`text-[9px] truncate px-1 py-0.5 bg-bay-950/80 ${style.text}`}>
              {c.name}
            </span>
          </button>
        );
      })}
    </div>
  );
}
