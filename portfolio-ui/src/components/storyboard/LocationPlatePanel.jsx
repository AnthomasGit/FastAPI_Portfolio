import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, ImageIcon, Expand, Check } from 'lucide-react';
import { api } from '../../lib/api';

// A location's wide, character-free establishing "plate" (Phase 4): the fixed
// background reused across every scene set here. The plate is chosen on the
// asset-library thumbnails below (the Frame button); this panel shows the
// current plate and lets you outpaint it wider, promoting the result.
const EXPAND_PRESETS = [
  { key: 'widen_21_9', label: 'Widen 21:9' },
  { key: 'pan_left', label: 'Pan left' },
  { key: 'pan_right', label: 'Pan right' },
];

export function LocationPlatePanel({ location, projectId }) {
  const queryClient = useQueryClient();
  const plateId = location.plate_asset_image_id;
  const [showExpand, setShowExpand] = useState(false);
  const [expandJobId, setExpandJobId] = useState(null);

  const invalidateProject = () =>
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });

  // Expand is async — poll its job to completion.
  const { data: job } = useQuery({
    queryKey: ['asset-image', expandJobId],
    queryFn: () => api.getAssetImage(expandJobId),
    enabled: !!expandJobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === 'completed' || s === 'failed' ? false : 2000;
    },
  });
  const expandDone = job?.status === 'completed';
  const expandFailed = job?.status === 'failed';
  const variantId = expandDone ? expandJobId : null;
  const expanding = !!expandJobId && !expandDone && !expandFailed;

  const expand = useMutation({
    mutationFn: (preset) => api.expandPlate(location.id, { preset }),
    onSuccess: (r) => { setShowExpand(false); setExpandJobId(r.asset_image_id); },
  });
  const promote = useMutation({
    mutationFn: (assetImageId) => api.setLocationPlate(location.id, assetImageId),
    onSuccess: () => { setExpandJobId(null); invalidateProject(); },
  });

  const busy = expanding || expand.isPending || promote.isPending;

  return (
    <div className="mt-2.5 pt-2.5 border-t border-line/60">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] uppercase tracking-wide text-fg-faint">Background plate</span>
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
      </div>

      {/* Preview: the wide plate matte (inset on bay-900). */}
      <div className="relative aspect-video rounded-frame border border-line bg-bay-900 overflow-hidden">
        {plateId ? (
          <img src={api.getAssetImageFile(plateId)} alt={`${location.name} plate`} className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center gap-1 px-2 text-center">
            <ImageIcon className="w-4 h-4 text-fg-faint" />
            <span className="text-[10px] text-fg-faint leading-tight">
              Set one from the library below (the frame button on a thumbnail).
            </span>
          </div>
        )}
        {busy && (
          <div className="absolute inset-0 flex items-center justify-center gap-1.5 bg-bay-950/70 text-[11px] text-fg-muted">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> {expanding ? 'Expanding…' : 'Saving…'}
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

      {(expand.isError || promote.isError || expandFailed) && (
        <p className="text-[10px] text-stop mt-1.5">Plate operation failed.</p>
      )}
    </div>
  );
}
