import { Loader2, Trash2 } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function PipelinePanel({ captures, isLoading, sceneId }) {
  const queryClient = useQueryClient();
  const deleteMutation = useMutation({
    mutationFn: (captureId) => api.deleteCapture(captureId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['captures', sceneId] }),
  });

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
        <div
          key={cap.id}
          className="bg-white/5 border border-white/10 rounded-lg p-3 space-y-2"
        >
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
                onClick={() => deleteMutation.mutate(cap.id)}
                className="p-1 rounded text-slate-500 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-40 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <p className="text-[10px] text-slate-500 mb-1">Depth</p>
              <img
                src={api.getCaptureDepthUrl(cap.id)}
                alt="Depth map"
                className="w-full aspect-video rounded border border-white/10 bg-black/40 object-cover"
              />
            </div>
            {cap.edge_map_url && (
              <div>
                <p className="text-[10px] text-slate-500 mb-1">Edge</p>
                <img
                  src={api.getCaptureDepthUrl(cap.id)}
                  alt="Edge map"
                  className="w-full aspect-video rounded border border-white/10 bg-black/40 object-cover"
                />
              </div>
            )}
          </div>

          <details className="text-[10px] text-slate-500">
            <summary className="cursor-pointer hover:text-slate-300">
              Camera
            </summary>
            <pre className="mt-1 bg-black/40 rounded p-2 overflow-x-auto text-[10px]">
              {JSON.stringify(cap.camera, null, 2)}
            </pre>
          </details>
        </div>
      ))}
    </div>
  );
}
