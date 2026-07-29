import { useEffect, useState } from 'react';
import { Loader2, Trash2, RotateCcw, Sparkles, Film } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

const STATUS_STYLES = {
  queued: 'bg-amber-500/15 text-amber-300',
  processing: 'bg-sky-500/15 text-sky-300',
  completed: 'bg-emerald-500/15 text-emerald-300',
  failed: 'bg-red-500/15 text-red-300',
};

// LTX gets a *motion* description; the still already carries the look. Prefilled
// so the field demonstrates its own format and the model never receives a static
// scene description in the motion slot.
const DEFAULT_MOTION = 'Gentle ambient motion, the camera holds steady.';

function StatusChip({ status }) {
  return (
    <span
      className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
        STATUS_STYLES[status] || 'bg-white/10 text-slate-300'
      }`}
    >
      {status}
    </span>
  );
}

// The three stages of a shot, read left to right. Each segment fills with its
// stage accent once that stage lands — pipeline progress legible at a glance
// down a column of capture cards.
function StageRail({ hasStill, stillInflight, hasClip, clipInflight }) {
  const seg = (filled, inflight, color) =>
    `h-1 flex-1 rounded-full transition-colors ${
      filled
        ? color
        : inflight
          ? `${color} opacity-40 animate-pulse motion-reduce:animate-none`
          : 'bg-white/10'
    }`;
  return (
    <div className="flex items-center gap-1" title="Capture → Still → Clip">
      <div className={seg(true, false, 'bg-slate-400')} />
      <div className={seg(hasStill, stillInflight, 'bg-indigo-400')} />
      <div className={seg(hasClip, clipInflight, 'bg-fuchsia-400')} />
    </div>
  );
}

// Drives the /generate/status poller for one non-terminal still; the DB status
// only advances when that endpoint is polled.
function GenerationPoller({ generationId, sceneId }) {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ['generation-status', generationId],
    queryFn: () => api.getGenerationStatus(generationId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'completed' || status === 'failed' ? false : 2000;
    },
  });

  useEffect(() => {
    if (data?.status === 'completed' || data?.status === 'failed') {
      queryClient.invalidateQueries({ queryKey: ['captures', sceneId] });
    }
  }, [data?.status, queryClient, sceneId]);

  return null;
}

// Same shape as GenerationPoller, slower cadence: clips take minutes, not
// seconds, so a 2s poll would just hammer the endpoint.
function VideoPoller({ videoId, sceneId }) {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ['video-status', videoId],
    queryFn: () => api.getVideoStatus(videoId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'completed' || status === 'failed' ? false : 5000;
    },
  });

  useEffect(() => {
    if (data?.status === 'completed' || data?.status === 'failed') {
      queryClient.invalidateQueries({ queryKey: ['captures', sceneId] });
    }
  }, [data?.status, queryClient, sceneId]);

  return null;
}

function CaptureCard({ cap, sceneId }) {
  const queryClient = useQueryClient();

  const attempts = [...(cap.generated_images || [])].sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at)
  );
  const inflight = attempts.some(
    (a) => a.status === 'queued' || a.status === 'processing'
  );
  const newestCompleted = attempts.find((a) => a.status === 'completed');

  const [selectedId, setSelectedId] = useState(null);
  const selected =
    attempts.find((a) => a.id === selectedId && a.status === 'completed') ||
    newestCompleted;

  // Clips hang off the selected still.
  const clips = [...(selected?.videos || [])].sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at)
  );
  const clipInflight = clips.some(
    (c) => c.status === 'queued' || c.status === 'processing'
  );
  const newestClip = clips.find((c) => c.status === 'completed');

  const [motionPrompt, setMotionPrompt] = useState(DEFAULT_MOTION);
  const [resultView, setResultView] = useState('still'); // 'still' | 'clip'

  // Snap the result view to a clip the moment a new one finishes, without an
  // effect: adjusting state during render is React's recommended way to react
  // to a changed value, and it still lets the Still/Clip toggle override.
  const [lastClipId, setLastClipId] = useState(null);
  if (newestClip && newestClip.id !== lastClipId) {
    setLastClipId(newestClip.id);
    setResultView('clip');
  }

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteCapture(cap.id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['captures', sceneId] }),
  });

  const generateMutation = useMutation({
    mutationFn: () => api.generateControlled(cap.id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['captures', sceneId] }),
  });

  const videoMutation = useMutation({
    mutationFn: () =>
      api.generateVideo(selected.id, { motionPrompt: motionPrompt.trim() }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['captures', sceneId] }),
  });

  // Stage render is what the beauty pass actually conditions on (the textured
  // color pass), not depth. Fall back to depth only if color wasn't captured.
  const stageRenderUrl = cap.color_map_url
    ? api.getCaptureColorUrl(cap.id)
    : api.getCaptureDepthUrl(cap.id);

  return (
    <div className="bg-white/5 border border-white/10 rounded-lg p-3 space-y-2">
      {attempts
        .filter((a) => a.status === 'queued' || a.status === 'processing')
        .map((a) => (
          <GenerationPoller key={a.id} generationId={a.id} sceneId={sceneId} />
        ))}
      {clips
        .filter((c) => c.status === 'queued' || c.status === 'processing')
        .map((c) => (
          <VideoPoller key={c.id} videoId={c.id} sceneId={sceneId} />
        ))}

      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-slate-400">
          {new Date(cap.created_at).toLocaleString()}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[10px] text-slate-500">
            {cap.width}x{cap.height}
          </span>
          <button
            type="button"
            title="Delete this capture"
            disabled={deleteMutation.isPending}
            onClick={() => deleteMutation.mutate()}
            className="p-1 rounded text-slate-500 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-40 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-red-400"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <StageRail
        hasStill={!!newestCompleted}
        stillInflight={inflight}
        hasClip={!!newestClip}
        clipInflight={clipInflight}
      />

      {/* Lineage: the render that steered this shot next to its result */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <p className="text-[10px] text-slate-500 mb-1">Stage render</p>
          <img
            src={stageRenderUrl}
            alt="Stage render (conditioning frame)"
            className="w-full aspect-video rounded border border-white/10 bg-black/40 object-cover"
          />
        </div>
        <div>
          <div className="flex items-center justify-between mb-1 h-3">
            <p className="text-[10px] text-slate-500">
              {resultView === 'clip' ? 'Clip' : 'Still'}
            </p>
            {newestClip && selected && (
              <div className="flex items-center gap-0.5" role="group" aria-label="Result view">
                <button
                  type="button"
                  aria-pressed={resultView === 'still'}
                  onClick={() => setResultView('still')}
                  className={`px-1 rounded text-[9px] leading-none py-0.5 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-indigo-400 ${
                    resultView === 'still'
                      ? 'bg-indigo-500/25 text-indigo-200'
                      : 'text-slate-500 hover:text-slate-300'
                  }`}
                >
                  Still
                </button>
                <button
                  type="button"
                  aria-pressed={resultView === 'clip'}
                  onClick={() => setResultView('clip')}
                  className={`px-1 rounded text-[9px] leading-none py-0.5 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-fuchsia-400 ${
                    resultView === 'clip'
                      ? 'bg-fuchsia-500/25 text-fuchsia-200'
                      : 'text-slate-500 hover:text-slate-300'
                  }`}
                >
                  Clip
                </button>
              </div>
            )}
          </div>
          {resultView === 'clip' && newestClip ? (
            <video
              src={api.getVideoFileUrl(newestClip.id)}
              controls
              loop
              muted
              playsInline
              className="w-full aspect-video rounded border border-white/10 bg-black/40 object-cover"
            />
          ) : selected ? (
            <img
              src={api.getGeneratedImageUrl(selected.id)}
              alt="Generated still"
              className="w-full aspect-video rounded border border-white/10 bg-black/40 object-cover"
            />
          ) : (
            <div className="w-full aspect-video rounded border border-white/10 bg-black/40 flex items-center justify-center">
              {inflight ? (
                <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none text-slate-500" />
              ) : (
                <span className="text-[10px] text-slate-600">No still yet</span>
              )}
            </div>
          )}
        </div>
      </div>

      {(cap.color_map_url || cap.depth_map_url || cap.normal_map_url || cap.seg_map_url || cap.clean_map_url) && (
        <details className="text-[10px] text-slate-500">
          <summary className="cursor-pointer hover:text-slate-300">Maps</summary>
          <div className="grid grid-cols-2 gap-2 mt-1">
            {cap.depth_map_url && (
              <div>
                <p className="text-[10px] text-slate-500 mb-1">Depth</p>
                <img
                  src={api.getCaptureDepthUrl(cap.id)}
                  alt="Depth map"
                  className="w-full aspect-video rounded border border-white/10 bg-black/40 object-cover"
                />
              </div>
            )}
            {cap.clean_map_url && (
              <div>
                <p className="text-[10px] text-slate-500 mb-1">Clean plate</p>
                <img
                  src={api.getCaptureCleanUrl(cap.id)}
                  alt="Clean plate (backdrop only)"
                  className="w-full aspect-video rounded border border-white/10 bg-black/40 object-cover"
                />
              </div>
            )}
            {cap.normal_map_url && (
              <div>
                <p className="text-[10px] text-slate-500 mb-1">Normal</p>
                <img
                  src={api.getCaptureNormalUrl(cap.id)}
                  alt="Normal map"
                  className="w-full aspect-video rounded border border-white/10 bg-black/40 object-cover"
                />
              </div>
            )}
            {cap.seg_map_url && (
              <div>
                <p className="text-[10px] text-slate-500 mb-1">Segmentation</p>
                <img
                  src={api.getCaptureSegUrl(cap.id)}
                  alt="Segmentation map"
                  className="w-full aspect-video rounded border border-white/10 bg-black/40 object-cover"
                />
              </div>
            )}
          </div>
        </details>
      )}

      {/* Beauty pass: turn the stage render into a photoreal, identity-corrected still */}
      <div className="space-y-1.5 pt-1 border-t border-white/10">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] text-slate-500">Beauty pass</span>
          <button
            type="button"
            disabled={inflight || generateMutation.isPending}
            onClick={() => generateMutation.mutate()}
            className="flex items-center gap-1 px-2 py-1 rounded bg-indigo-500/20 text-indigo-300 hover:bg-indigo-500/30 disabled:opacity-40 text-[10px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-indigo-400"
          >
            {inflight || generateMutation.isPending ? (
              <Loader2 className="w-3 h-3 animate-spin motion-reduce:animate-none" />
            ) : (
              <Sparkles className="w-3 h-3" />
            )}
            {newestCompleted ? 'Regenerate still' : 'Generate still'}
          </button>
        </div>
        {generateMutation.isError && (
          <p className="text-[10px] text-red-400">
            {generateMutation.error.message}
          </p>
        )}
      </div>

      {/* Video: animate a completed still into a clip */}
      {selected && (
        <div className="space-y-1.5 pt-1 border-t border-white/10">
          <span className="text-[10px] text-slate-500">Motion</span>
          <textarea
            value={motionPrompt}
            onChange={(e) => setMotionPrompt(e.target.value)}
            rows={2}
            placeholder={DEFAULT_MOTION}
            disabled={clipInflight || videoMutation.isPending}
            className="w-full text-[10px] bg-black/40 border border-white/10 rounded px-2 py-1 text-slate-200 resize-none focus:outline-none focus-visible:ring-1 focus-visible:ring-fuchsia-400 disabled:opacity-40"
          />
          <button
            type="button"
            disabled={clipInflight || videoMutation.isPending || !motionPrompt.trim()}
            onClick={() => videoMutation.mutate()}
            className="w-full flex items-center justify-center gap-1 px-2 py-1 rounded bg-fuchsia-500/20 text-fuchsia-300 hover:bg-fuchsia-500/30 disabled:opacity-40 text-[10px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-fuchsia-400"
          >
            {clipInflight || videoMutation.isPending ? (
              <Loader2 className="w-3 h-3 animate-spin motion-reduce:animate-none" />
            ) : (
              <Film className="w-3 h-3" />
            )}
            {newestClip ? 'Regenerate clip' : 'Generate clip'}
          </button>
          {videoMutation.isError && (
            <p className="text-[10px] text-red-400">
              {videoMutation.error.message}
            </p>
          )}
          {clips.some((c) => c.status === 'failed' && c.error) && (
            <p className="text-[10px] text-red-400/80 break-words">
              {clips.find((c) => c.status === 'failed' && c.error).error}
            </p>
          )}
        </div>
      )}

      {attempts.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] text-slate-500">Attempts</p>
          {attempts.map((a) => (
            <div
              key={a.id}
              className={`flex items-center justify-between gap-2 px-2 py-1 rounded text-[10px] ${
                selected?.id === a.id ? 'bg-white/10' : 'bg-black/20'
              } ${a.status === 'completed' ? 'cursor-pointer hover:bg-white/10' : ''}`}
              onClick={() => a.status === 'completed' && setSelectedId(a.id)}
            >
              <div className="flex items-center gap-2 min-w-0">
                <StatusChip status={a.status} />
                <span className="text-slate-500 truncate">
                  {new Date(a.created_at).toLocaleTimeString()}
                  {a.videos?.length > 0 && ` · ${a.videos.length} clip${a.videos.length > 1 ? 's' : ''}`}
                </span>
              </div>
              {a.status === 'failed' && (
                <button
                  type="button"
                  title={a.error || 'Retry'}
                  disabled={inflight || generateMutation.isPending}
                  onClick={(e) => {
                    e.stopPropagation();
                    generateMutation.mutate();
                  }}
                  className="flex items-center gap-1 px-1.5 py-0.5 rounded text-slate-400 hover:text-slate-200 hover:bg-white/10 disabled:opacity-40 transition-colors shrink-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-slate-400"
                >
                  <RotateCcw className="w-3 h-3" />
                  Retry
                </button>
              )}
            </div>
          ))}
          {attempts.find((a) => a.status === 'failed' && a.error) && (
            <p className="text-[10px] text-red-400/80 break-words">
              {attempts.find((a) => a.status === 'failed' && a.error).error}
            </p>
          )}
        </div>
      )}

      <details className="text-[10px] text-slate-500">
        <summary className="cursor-pointer hover:text-slate-300">Camera</summary>
        <pre className="mt-1 bg-black/40 rounded p-2 overflow-x-auto text-[10px]">
          {JSON.stringify(cap.camera, null, 2)}
        </pre>
      </details>
    </div>
  );
}

export function PipelinePanel({ captures, isLoading, sceneId }) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none text-slate-400" />
      </div>
    );
  }

  if (!captures || captures.length === 0) {
    return (
      <p className="text-xs text-slate-500">
        No captures yet. Frame your shot and click Capture.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {captures.map((cap) => (
        <CaptureCard key={cap.id} cap={cap} sceneId={sceneId} />
      ))}
    </div>
  );
}
