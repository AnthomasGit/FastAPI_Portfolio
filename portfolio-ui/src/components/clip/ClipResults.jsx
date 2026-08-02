import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Film } from 'lucide-react';
import { api } from '../../lib/api';

const STATUS_STYLE = {
  queued: 'bg-amber-500/15 text-amber-300',
  processing: 'bg-sky-500/15 text-sky-300',
  completed: 'bg-emerald-500/15 text-emerald-300',
  failed: 'bg-red-500/15 text-red-300',
};

// Poll one in-flight clip and refresh the shot once it settles.
// The invalidate lives in an effect, not the render body — invalidating during
// render (as the older shot-list poller does) schedules work mid-commit.
function ClipPoller({ videoId, onSettled }) {
  const { data } = useQuery({
    queryKey: ['video-status', videoId],
    queryFn: () => api.getVideoStatus(videoId),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === 'completed' || s === 'failed' ? false : 5000;
    },
  });
  useEffect(() => {
    if (data?.status === 'completed' || data?.status === 'failed') onSettled(data);
  }, [data, onSettled]);
  return null;
}

export function ClipResults({ clips, sceneId, shotId, onClipCompleted }) {
  const queryClient = useQueryClient();
  const inflight = clips.filter((c) => c.status === 'queued' || c.status === 'processing');

  const handleSettled = (video) => {
    queryClient.invalidateQueries({ queryKey: ['shots', sceneId] });
    queryClient.invalidateQueries({ queryKey: ['shot', shotId] });
    if (video?.status === 'completed') onClipCompleted?.(video);
  };

  if (!clips.length) {
    return (
      <div className="rounded-lg border border-dashed border-white/10 bg-black/20 p-6 text-center">
        <Film className="w-5 h-5 text-slate-700 mx-auto mb-2" />
        <p className="text-[11px] text-slate-500">
          No clips yet. Pick a workflow, choose references, and generate.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {inflight.map((c) => (
        <ClipPoller key={c.id} videoId={c.id} onSettled={handleSettled} />
      ))}

      {clips.map((clip) => (
        <div key={clip.id} className="rounded-lg border border-white/10 bg-black/40 overflow-hidden">
          {clip.status === 'completed' ? (
            <video
              src={api.getVideoFileUrl(clip.id)}
              controls
              loop
              muted
              playsInline
              className="w-full aspect-video bg-black object-contain"
            />
          ) : (
            <div className="w-full aspect-video bg-black/60 flex items-center justify-center">
              <Film
                className={`w-6 h-6 ${
                  clip.status === 'failed'
                    ? 'text-red-500/50'
                    : 'text-slate-700 animate-pulse motion-reduce:animate-none'
                }`}
              />
            </div>
          )}
          <div className="flex items-center gap-2 px-2 py-1.5">
            <span
              className={`text-[9px] font-medium px-1.5 py-0.5 rounded-full ${
                STATUS_STYLE[clip.status] || 'bg-white/5 text-slate-400'
              }`}
            >
              {clip.status}
            </span>
            {clip.params?.workflow && (
              <span className="text-[9px] text-slate-500">{clip.params.workflow}</span>
            )}
            <span className="text-[9px] text-slate-600 ml-auto">
              {new Date(clip.created_at).toLocaleTimeString()}
            </span>
          </div>
          {clip.error && (
            <p className="text-[9px] text-red-400/80 break-words px-2 pb-2">{clip.error}</p>
          )}
        </div>
      ))}
    </div>
  );
}
