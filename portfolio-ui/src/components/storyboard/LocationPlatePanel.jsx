import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, ImageIcon, Expand, Check, Images } from 'lucide-react';
import { api } from '../../lib/api';

// A location's wide, character-free establishing "plate" (Phase 4): the fixed
// background reused across every scene set here. The plate is CHOSEN from the
// location's asset library (generate new images via the (+) below); Expand
// outpaints the current plate into a new variant the user then promotes.
const EXPAND_PRESETS = [
  { key: 'widen_21_9', label: 'Widen 21:9' },
  { key: 'pan_left', label: 'Pan left' },
  { key: 'pan_right', label: 'Pan right' },
];

export function LocationPlatePanel({ location, projectId }) {
  const queryClient = useQueryClient();
  const plateId = location.plate_asset_image_id;
  const [picking, setPicking] = useState(false);
  const [showExpand, setShowExpand] = useState(false);
  const [expandJobId, setExpandJobId] = useState(null);

  const invalidateProject = () =>
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });

  // The location's library: references backed by a generated asset image (only
  // those can be a plate — the FK points at an AssetImage).
  const { data: refs } = useQuery({
    queryKey: ['references', 'locations', location.id],
    queryFn: () => api.listReferences('locations', location.id),
  });
  const library = (refs || []).filter((r) => r.asset_image_id);

  // Expand is the one async path left — poll its job to completion.
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

  const choose = useMutation({
    mutationFn: (assetImageId) => api.setLocationPlate(location.id, assetImageId),
    onSuccess: () => { setPicking(false); invalidateProject(); },
  });
  const expand = useMutation({
    mutationFn: (preset) => api.expandPlate(location.id, { preset }),
    onSuccess: (r) => { setShowExpand(false); setExpandJobId(r.asset_image_id); },
  });
  const promote = useMutation({
    mutationFn: (assetImageId) => api.setLocationPlate(location.id, assetImageId),
    onSuccess: () => { setExpandJobId(null); invalidateProject(); },
  });

  const busy = expanding || choose.isPending || expand.isPending || promote.isPending;
  const showPicker = picking || !plateId;

  return (
    <div className="mt-2.5 pt-2.5 border-t border-line/60">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] uppercase tracking-wide text-fg-faint">Background plate</span>
        {plateId && !busy && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setShowExpand((v) => !v)}
              title="Expand / outpaint the plate"
              className="flex items-center gap-1 h-5 px-1.5 rounded-frame border border-line text-[10px] text-fg-faint hover:text-fg hover:border-set transition-colors"
            >
              <Expand className="w-3 h-3" /> Expand
            </button>
            <button
              type="button"
              onClick={() => setPicking((v) => !v)}
              title="Choose a different plate from the library"
              className="flex items-center gap-1 h-5 px-1.5 rounded-frame border border-line text-[10px] text-fg-faint hover:text-fg hover:border-set transition-colors"
            >
              <Images className="w-3 h-3" /> Change
            </button>
          </div>
        )}
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
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> {expanding ? 'Expanding…' : 'Saving…'}
          </div>
        )}
      </div>

      {/* Library picker: choose the plate from existing location images. */}
      {showPicker && !busy && (
        <div className="mt-1.5">
          {library.length === 0 ? (
            <p className="text-[11px] text-fg-faint">
              No images in the library yet — use the <span className="text-fg-muted">+</span> below to generate one.
            </p>
          ) : (
            <>
              <span className="text-[10px] uppercase tracking-wide text-fg-faint">Select from library</span>
              <div className="grid grid-cols-3 gap-1.5 mt-1">
                {library.map((ref) => {
                  const isCurrent = ref.asset_image_id === plateId;
                  return (
                    <button
                      key={ref.id}
                      type="button"
                      onClick={() => choose.mutate(ref.asset_image_id)}
                      title={isCurrent ? 'Current plate' : 'Use as plate'}
                      className={`group relative aspect-video rounded-frame border overflow-hidden transition-colors ${
                        isCurrent ? 'border-set' : 'border-line hover:border-set/60'
                      }`}
                    >
                      <img src={api.getAssetImageFile(ref.asset_image_id)} alt="" className="w-full h-full object-cover" />
                      {isCurrent && (
                        <span className="absolute top-0.5 right-0.5 w-4 h-4 rounded flex items-center justify-center text-set">
                          <Check className="w-3 h-3" />
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}

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

      {(choose.isError || expand.isError || promote.isError || expandFailed) && (
        <p className="text-[10px] text-stop mt-1.5">Plate operation failed.</p>
      )}
    </div>
  );
}
