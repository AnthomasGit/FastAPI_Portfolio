import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { Film, Loader2, ImageIcon } from 'lucide-react';
import { api } from '../../lib/api';
import { allClips } from './shotReadiness';

// Polls one in-flight clip and refreshes the shot list when it settles.
// The invalidate is in an effect: calling it during render schedules a store
// update mid-commit, which React warns about and can loop.
function ClipPoller({ videoId, sceneId }) {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ['video-status', videoId],
    queryFn: () => api.getVideoStatus(videoId),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === 'completed' || s === 'failed' ? false : 5000;
    },
  });
  useEffect(() => {
    if (data?.status === 'completed' || data?.status === 'failed') {
      queryClient.invalidateQueries({ queryKey: ['shots', sceneId] });
    }
  }, [data?.status, queryClient, sceneId]);
  return null;
}

export function ShotStillCell({ shot, sceneId, availableStills }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { id: projectId } = useParams();
  const still = shot.still;
  // Clips reach a shot two ways depending on the workflow that made them, so
  // read both: reference-driven ones attach to the shot, still-driven ones
  // hang off the still.
  const clips = allClips(shot);
  const clipInflight = clips.some((c) => c.status === 'queued' || c.status === 'processing');
  const newestClip = clips.find((c) => c.status === 'completed');
  const clipError = clips.find((c) => c.status === 'failed' && c.error);

  const [picking, setPicking] = useState(false);
  const [view, setView] = useState('still'); // 'still' | 'clip'

  const attachMut = useMutation({
    mutationFn: (imageId) => api.updateShot(shot.id, { generated_image_id: imageId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shots', sceneId] });
      setPicking(false);
    },
  });

  return (
    <div className="w-40 space-y-1.5">
      {clips
        .filter((c) => c.status === 'queued' || c.status === 'processing')
        .map((c) => (
          <ClipPoller key={c.id} videoId={c.id} sceneId={sceneId} />
        ))}

      <div className="aspect-video rounded border border-line bg-bay-900 overflow-hidden flex items-center justify-center">
        {view === 'clip' && newestClip ? (
          <video
            src={api.getVideoFileUrl(newestClip.id)}
            controls loop muted playsInline
            className="w-full h-full object-cover"
          />
        ) : still ? (
          <img
            src={api.getGeneratedImageUrl(still.id)}
            alt="Shot still"
            className="w-full h-full object-cover"
          />
        ) : (
          <ImageIcon className="w-5 h-5 text-fg-faint" />
        )}
      </div>

      {/* Still / Clip toggle appears once a clip exists */}
      {newestClip && (
        <div className="flex items-center gap-0.5" role="group" aria-label="Result view">
          {['still', 'clip'].map((v) => (
            <button
              key={v}
              aria-pressed={view === v}
              onClick={() => setView(v)}
              className={`px-1.5 rounded text-[9px] py-0.5 capitalize transition-colors focus-visible:outline-none focus-visible:ring-1 ${
                view === v
                  ? v === 'clip'
                    ? 'bg-clip/60 text-clip focus-visible:ring-clip'
                    : 'bg-clip/20 text-clip focus-visible:ring-clip'
                  : 'text-fg-muted hover:text-fg focus-visible:ring-bay-600'
              }`}
            >
              {v}
            </button>
          ))}
        </div>
      )}

      {picking ? (
        <select
          autoFocus
          onChange={(e) => e.target.value && attachMut.mutate(e.target.value)}
          onBlur={() => setPicking(false)}
          className="w-full text-[10px] bg-bay-900 border border-line rounded text-fg py-1 focus:outline-none"
        >
          <option value="">Pick a still…</option>
          {availableStills.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
      ) : (
        <button
          onClick={() => setPicking(true)}
          className="w-full text-[10px] text-fg-muted hover:text-fg border border-line rounded py-1 hover:bg-bay-800 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bay-600"
        >
          {still ? 'Change still' : 'Attach still'}
        </button>
      )}

      {/* Always available: reference-driven workflows need no still, so the
          Clip Studio is reachable even before a beauty pass exists. */}
      <button
        onClick={() =>
          navigate(`/project/${projectId}/scene/${sceneId}/shot/${shot.id}/clip`)
        }
        className="w-full flex items-center justify-center gap-1 px-2 py-1 rounded bg-clip/60 text-clip hover:bg-clip/60 text-[10px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-clip"
      >
        {clipInflight ? (
          <Loader2 className="w-3 h-3 animate-spin motion-reduce:animate-none" />
        ) : (
          <Film className="w-3 h-3" />
        )}
        {clipInflight ? 'Generating…' : newestClip ? 'Regenerate clip' : 'Generate clip'}
      </button>
      {clipError && (
        <p className="text-[9px] text-stop/80 break-words">{clipError.error}</p>
      )}
    </div>
  );
}
