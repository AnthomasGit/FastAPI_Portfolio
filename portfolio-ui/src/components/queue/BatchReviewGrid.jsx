import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Trash2, Save, Check } from 'lucide-react';
import { api } from '@/lib/api';

// Review a finished batch before anything is linked to an entity: the grid is
// the whole output, hover-delete rejects, "Save all" commits the survivors.
// Rejection is a real delete — the artifact list is derived from what still
// exists, so no extra "kept" state has to be tracked anywhere.

function Tile({ item, onReject, rejecting }) {
  const isClip = item.artifact_type === 'generated_video';
  return (
    <div className="group relative rounded-frame border border-line bg-bay-900 overflow-hidden">
      <div className="aspect-square flex items-center justify-center bg-bay-950">
        {item.url ? (
          isClip ? (
            <video src={item.url} muted loop playsInline
              onMouseEnter={(e) => e.currentTarget.play?.()}
              onMouseLeave={(e) => e.currentTarget.pause?.()}
              className="w-full h-full object-contain" />
          ) : (
            <img src={item.url} alt="" loading="lazy" className="w-full h-full object-contain" />
          )
        ) : (
          <span className="text-[10px] text-fg-faint">no file</span>
        )}
      </div>

      <div className="px-2 py-1.5 border-t border-line">
        <p className="font-mono text-[10px] text-fg truncate">
          {item.target?.name || item.target?.type || item.job_kind}
        </p>
        {item.slot && <p className="text-[10px] text-fg-faint truncate">{item.slot}</p>}
      </div>

      {!item.committed && (
        <button
          onClick={() => onReject(item)}
          disabled={rejecting}
          title="Delete this result"
          className="absolute top-1.5 right-1.5 p-1 rounded border border-stop/40 bg-bay-950/80
                     text-stop opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
        >
          {rejecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
        </button>
      )}
    </div>
  );
}

export function BatchReviewGrid({ batch, projectId }) {
  const queryClient = useQueryClient();
  const [rejectingId, setRejectingId] = useState(null);

  const { data, isLoading } = useQuery({
    queryKey: ['batch-artifacts', batch.id],
    queryFn: () => api.getBatchArtifacts(batch.id),
  });
  const artifacts = data?.artifacts || [];

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['batch-artifacts', batch.id] });
    queryClient.invalidateQueries({ queryKey: ['project-batches', projectId] });
  };

  const reject = useMutation({
    mutationFn: (item) =>
      item.artifact_type === 'generated_video'
        ? api.deleteVideo(item.id)
        : api.deleteAssetImage(item.id),
    onMutate: (item) => setRejectingId(item.id),
    onSettled: () => { setRejectingId(null); refresh(); },
  });

  const commit = useMutation({
    mutationFn: () => api.commitBatch(batch.id),
    onSuccess: () => {
      refresh();
      // Canonical/plate thumbnails elsewhere in the app may have just changed.
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      queryClient.invalidateQueries({ queryKey: ['asset-images'] });
    },
  });

  if (isLoading) {
    return (
      <div className="flex justify-center p-6">
        <Loader2 className="w-4 h-4 animate-spin text-lead-500" />
      </div>
    );
  }
  if (!artifacts.length) {
    return <p className="px-4 py-3 text-xs text-fg-faint">This batch produced nothing to review.</p>;
  }

  const committed = !!batch.committed_at;

  return (
    <div className="p-3">
      <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2">
        {artifacts.map((item) => (
          <Tile key={`${item.artifact_type}:${item.id}`} item={item}
            onReject={reject.mutate} rejecting={rejectingId === item.id} />
        ))}
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-line pt-3">
        <span className="text-[11px] text-fg-faint">
          {committed
            ? 'Saved to the library'
            : `${artifacts.length} result${artifacts.length === 1 ? '' : 's'} — delete the misses, then save`}
        </span>
        {committed ? (
          <span className="flex items-center gap-1 text-[11px] text-cast">
            <Check className="w-3 h-3" /> committed
          </span>
        ) : (
          <button
            onClick={() => commit.mutate()}
            disabled={commit.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-frame bg-lead-500 text-bay-950
                       text-xs font-semibold hover:bg-lead-400 transition-colors disabled:opacity-50"
          >
            {commit.isPending
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <Save className="w-3.5 h-3.5" />}
            Save all
          </button>
        )}
      </div>

      {commit.isError && (
        <p role="alert" className="mt-2 rounded-frame border border-stop/40 bg-stop/10 px-3 py-2 text-xs text-stop">
          Couldn’t save: {commit.error?.message || 'unknown error'}
        </p>
      )}
    </div>
  );
}
