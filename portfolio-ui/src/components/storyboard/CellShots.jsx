import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Film } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../../lib/api';

// Read-only overview: the stills attached to this scene's shots, each with an
// option to play its clip. All generation lives on the Scene Detail page — this
// column is a visual glance, so a click either flips a still to its clip or
// (when empty) routes to Scene Detail to start planning.
function ShotThumb({ shot }) {
  const still = shot.still;
  const clip = (still?.videos || []).find((v) => v.status === 'completed');
  const [showClip, setShowClip] = useState(false);

  if (!still) return null;

  return (
    <button
      type="button"
      onClick={() => clip && setShowClip((v) => !v)}
      title={clip ? 'Toggle clip' : shot.shot_number || 'Shot'}
      className={`relative w-12 h-8 rounded overflow-hidden border border-line bg-bay-900 ${clip ? 'cursor-pointer' : 'cursor-default'} focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-clip`}
    >
      {showClip && clip ? (
        <video src={api.getVideoFileUrl(clip.id)} loop muted autoPlay playsInline className="w-full h-full object-cover" />
      ) : (
        <img src={api.getGeneratedImageUrl(still.id)} alt="" className="w-full h-full object-cover" />
      )}
      {clip && !showClip && (
        <span className="absolute bottom-0 right-0 bg-bay-950/80 rounded-tl p-0.5">
          <Film className="w-2.5 h-2.5 text-clip" />
        </span>
      )}
    </button>
  );
}

export function CellShots({ scene, projectId }) {
  const { data: shots = [] } = useQuery({
    queryKey: ['shots', scene.id],
    queryFn: () => api.listShots(scene.id),
  });
  const withStills = shots.filter((s) => s.still);

  if (withStills.length === 0) {
    return (
      <Link
        to={`/project/${projectId}/scene/${scene.id}`}
        className="text-[10px] text-fg-faint hover:text-lead-500 transition-colors"
      >
        No shots yet
      </Link>
    );
  }

  return (
    <div className="flex flex-wrap gap-1">
      {withStills.map((shot) => (
        <ShotThumb key={shot.id} shot={shot} />
      ))}
    </div>
  );
}
