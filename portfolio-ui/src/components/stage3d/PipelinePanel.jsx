import { useEffect, useState } from 'react';
import { Loader2, Trash2, RotateCcw, Sparkles } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Slider } from '@/components/ui/slider';

const STATUS_STYLES = {
  queued: 'bg-amber-500/15 text-amber-300',
  processing: 'bg-sky-500/15 text-sky-300',
  completed: 'bg-emerald-500/15 text-emerald-300',
  failed: 'bg-red-500/15 text-red-300',
};

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

// Drives the existing /generate/status poller for one non-terminal attempt;
// the DB status only advances when that endpoint is polled.
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

  const [strength, setStrength] = useState(
    () => attempts[0]?.params?.controlnet_strength ?? 0.8
  );

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteCapture(cap.id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['captures', sceneId] }),
  });

  const generateMutation = useMutation({
    mutationFn: (params) => api.generateControlled(cap.id, { params }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['captures', sceneId] }),
  });

  return (
    <div className="bg-white/5 border border-white/10 rounded-lg p-3 space-y-2">
      {attempts
        .filter((a) => a.status === 'queued' || a.status === 'processing')
        .map((a) => (
          <GenerationPoller key={a.id} generationId={a.id} sceneId={sceneId} />
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
            className="p-1 rounded text-slate-500 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-40 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Lineage: conditioning depth next to the image it steered */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <p className="text-[10px] text-slate-500 mb-1">Depth</p>
          <img
            src={api.getCaptureDepthUrl(cap.id)}
            alt="Depth map"
            className="w-full aspect-video rounded border border-white/10 bg-black/40 object-cover"
          />
        </div>
        <div>
          <p className="text-[10px] text-slate-500 mb-1">Generated</p>
          {selected ? (
            <img
              src={api.getGeneratedImageUrl(selected.id)}
              alt="Generated image"
              className="w-full aspect-video rounded border border-white/10 bg-black/40 object-cover"
            />
          ) : (
            <div className="w-full aspect-video rounded border border-white/10 bg-black/40 flex items-center justify-center">
              {inflight ? (
                <Loader2 className="w-4 h-4 animate-spin text-slate-500" />
              ) : (
                <span className="text-[10px] text-slate-600">No image yet</span>
              )}
            </div>
          )}
        </div>
      </div>

      {(cap.color_map_url || cap.normal_map_url || cap.seg_map_url || cap.clean_map_url) && (
        <details className="text-[10px] text-slate-500">
          <summary className="cursor-pointer hover:text-slate-300">Maps</summary>
          <div className="grid grid-cols-2 gap-2 mt-1">
            {cap.color_map_url && (
              <div>
                <p className="text-[10px] text-slate-500 mb-1">Color</p>
                <img
                  src={api.getCaptureColorUrl(cap.id)}
                  alt="Color frame"
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

      {/* Controlled generation */}
      <div className="space-y-1.5 pt-1 border-t border-white/10">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] text-slate-500">
            ControlNet strength: {strength.toFixed(2)}
          </span>
          <button
            type="button"
            disabled={inflight || generateMutation.isPending}
            onClick={() =>
              generateMutation.mutate({ controlnet_strength: strength })
            }
            className="flex items-center gap-1 px-2 py-1 rounded bg-indigo-500/20 text-indigo-300 hover:bg-indigo-500/30 disabled:opacity-40 text-[10px] font-medium transition-colors"
          >
            {inflight || generateMutation.isPending ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Sparkles className="w-3 h-3" />
            )}
            Generate
          </button>
        </div>
        <Slider
          value={[strength]}
          min={0}
          max={1}
          step={0.05}
          disabled={inflight || generateMutation.isPending}
          onValueChange={([v]) => setStrength(v)}
        />
        {generateMutation.isError && (
          <p className="text-[10px] text-red-400">
            {generateMutation.error.message}
          </p>
        )}
      </div>

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
                  {a.params?.controlnet_strength != null &&
                    ` · s=${a.params.controlnet_strength}`}
                </span>
              </div>
              {a.status === 'failed' && (
                <button
                  type="button"
                  title={a.error || 'Retry with the same settings'}
                  disabled={inflight || generateMutation.isPending}
                  onClick={(e) => {
                    e.stopPropagation();
                    generateMutation.mutate({
                      controlnet_strength:
                        a.params?.controlnet_strength ?? strength,
                    });
                  }}
                  className="flex items-center gap-1 px-1.5 py-0.5 rounded text-slate-400 hover:text-slate-200 hover:bg-white/10 disabled:opacity-40 transition-colors shrink-0"
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
        <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
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
