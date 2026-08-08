import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, ImageIcon, Sparkles, Expand, Check } from 'lucide-react';
import { api } from '../../lib/api';

// A location's wide, character-free establishing "plate" (Phase 4): the fixed
// background reused across every scene set here. Lives in the Storyboard
// Locations tab alongside EntityAssetLibrary. Generate is async (the worker
// sets Location.plate on completion); Expand produces a NEW variant linked to
// the source that the user explicitly promotes with "Use as plate".
const EXPAND_PRESETS = [
  { key: 'widen_21_9', label: 'Widen 21:9' },
  { key: 'pan_left', label: 'Pan left' },
  { key: 'pan_right', label: 'Pan right' },
];

export function LocationPlatePanel({ location, projectId }) {
  const queryClient = useQueryClient();
  const plateId = location.plate_asset_image_id;
  // The in-flight job: { id, kind: 'generate' | 'expand' }.
  const [pending, setPending] = useState(null);
  const [showExpand, setShowExpand] = useState(false);

  const invalidateProject = () =>
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });

  // Poll the in-flight job until it terminates (mirrors SetImageDialog).
  const { data: job } = useQuery({
    queryKey: ['asset-image', pending?.id],
    queryFn: () => api.getAssetImage(pending.id),
    enabled: !!pending,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === 'completed' || s === 'failed' ? false : 2000;
    },
  });

  const done = job?.status === 'completed';
  const failed = job?.status === 'failed';
  // A completed expand is a variant awaiting promotion (derived, not stored).
  const variantId = pending?.kind === 'expand' && done ? pending.id : null;

  // When a *generate* completes, the worker has set Location.plate — refresh the
  // project so the new plate renders. Side-effect only (no setState in effect).
  useEffect(() => {
    if (pending?.kind === 'generate' && done) invalidateProject();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done, pending?.kind, projectId]);

  const generate = useMutation({
    mutationFn: () => api.generatePlate(location.id),
    onSuccess: (r) => setPending({ id: r.asset_image_id, kind: 'generate' }),
  });
  const expand = useMutation({
    mutationFn: (preset) => api.expandPlate(location.id, { preset }),
    onSuccess: (r) => { setShowExpand(false); setPending({ id: r.asset_image_id, kind: 'expand' }); },
  });
  const promote = useMutation({
    mutationFn: (assetImageId) => api.setLocationPlate(location.id, assetImageId),
    onSuccess: () => { setPending(null); invalidateProject(); },
  });

  const busy = (!!pending && !done && !failed)
    || generate.isPending || expand.isPending || promote.isPending;
  const busyLabel = pending?.kind === 'expand' ? 'Expanding…' : 'Generating…';

  return (
    <div className="mt-2.5 pt-2.5 border-t border-line/60">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] uppercase tracking-wide text-fg-faint">Background plate</span>
        <div className="flex items-center gap-1">
          {plateId && !busy && (
            <button
              type="button"
              onClick={() => setShowExpand((v) => !v)}
              title="Expand / outpaint the plate"
              className="flex items-center gap-1 h-5 px-1.5 rounded-frame border border-line text-[10px] text-fg-faint hover:text-fg hover:border-set transition-colors"
            >
              <Expand className="w-3 h-3" /> Expand
            </button>
          )}
          <button
            type="button"
            onClick={() => generate.mutate()}
            disabled={busy}
            title={plateId ? 'Regenerate plate' : 'Generate plate'}
            className="flex items-center gap-1 h-5 px-1.5 rounded-frame border border-line text-[10px] text-fg-faint hover:text-lead-400 hover:border-lead-600 transition-colors disabled:opacity-50"
          >
            <Sparkles className="w-3 h-3" /> {plateId ? 'Regenerate' : 'Generate'}
          </button>
        </div>
      </div>

      {/* Preview: the wide plate matte (inset on bay-900). */}
      <div className="relative aspect-video rounded-frame border border-line bg-bay-900 overflow-hidden">
        {plateId ? (
          <img src={api.getAssetImageFile(plateId)} alt={`${location.name} plate`} className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <ImageIcon className="w-4 h-4 text-fg-faint" />
          </div>
        )}
        {busy && (
          <div className="absolute inset-0 flex items-center justify-center gap-1.5 bg-bay-950/70 text-[11px] text-fg-muted">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> {busyLabel}
          </div>
        )}
      </div>

      {/* Expand presets. */}
      {showExpand && plateId && !busy && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {EXPAND_PRESETS.map((p) => (
            <button
              key={p.key}
              type="button"
              onClick={() => expand.mutate(p.key)}
              className="h-5 px-1.5 rounded-frame border border-line text-[10px] text-fg-muted hover:text-fg hover:border-set transition-colors"
            >
              {p.label}
            </button>
          ))}
        </div>
      )}

      {/* An expanded variant awaiting promotion to the active plate. */}
      {variantId && (
        <div className="flex items-center gap-2 mt-1.5">
          <div className="relative w-16 aspect-video rounded-frame border border-set/50 bg-bay-900 overflow-hidden shrink-0">
            <img src={api.getAssetImageFile(variantId)} alt="Expanded plate" className="w-full h-full object-cover" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[10px] text-fg-muted leading-tight">Expanded variant ready.</p>
            <button
              type="button"
              onClick={() => promote.mutate(variantId)}
              disabled={promote.isPending}
              className="mt-1 flex items-center gap-1 h-5 px-1.5 rounded-frame border border-lead-600 text-[10px] text-lead-400 hover:bg-lead-600/10 transition-colors disabled:opacity-50"
            >
              <Check className="w-3 h-3" /> Use as plate
            </button>
          </div>
        </div>
      )}

      {(generate.isError || expand.isError || promote.isError || failed) && (
        <p className="text-[10px] text-stop mt-1.5">Plate operation failed.</p>
      )}
    </div>
  );
}
