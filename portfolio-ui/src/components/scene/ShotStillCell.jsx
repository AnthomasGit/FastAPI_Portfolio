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

      <div className="aspect-video rounded border border-white/10 bg-black/50 overflow-hidden flex items-center justify-center">
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
          <ImageIcon className="w-5 h-5 text-slate-700" />
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
                    ? 'bg-fuchsia-500/25 text-fuchsia-200 focus-visible:ring-fuchsia-400'
                    : 'bg-indigo-500/25 text-indigo-200 focus-visible:ring-indigo-400'
                  : 'text-slate-500 hover:text-slate-300 focus-visible:ring-white/30'
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
          className="w-full text-[10px] bg-black/60 border border-white/10 rounded text-slate-200 py-1 focus:outline-none"
        >
          <option value="">Pick a still…</option>
          {availableStills.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
      ) : (
        <button
          onClick={() => setPicking(true)}
          className="w-full text-[10px] text-slate-400 hover:text-slate-200 border border-white/10 rounded py-1 hover:bg-white/5 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/30"
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
        className="w-full flex items-center justify-center gap-1 px-2 py-1 rounded bg-fuchsia-500/20 text-fuchsia-300 hover:bg-fuchsia-500/30 text-[10px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-fuchsia-400"
      >
        {clipInflight ? (
          <Loader2 className="w-3 h-3 animate-spin motion-reduce:animate-none" />
        ) : (
          <Film className="w-3 h-3" />
        )}
        {clipInflight ? 'Generating…' : newestClip ? 'Regenerate clip' : 'Generate clip'}
      </button>
      {clipError && (
        <p className="text-[9px] text-red-400/80 break-words">{clipError.error}</p>
      )}
    </div>
  );
}
