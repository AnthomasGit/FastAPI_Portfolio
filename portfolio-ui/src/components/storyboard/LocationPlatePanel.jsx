import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, ImageIcon, Expand, Check, Orbit, RefreshCw, Trash2 } from 'lucide-react';
import { api } from '../../lib/api';

// A location's wide, character-free establishing "plate" (Phase 4).
//
// There is no project-wide "active plate" any more: which image a location uses
// is a per-scene choice, made with the scene page's "Primary for this scene"
// picker. This panel therefore shows the location's MOST RECENT image — the one
// a scene inherits when it has not picked — and lets you outpaint it wider or
// fan it out to 360 angles. "Use as plate" adds the result to the library,
// which makes it the newest and so the new default.
const EXPAND_PRESETS = [
  { key: 'widen_21_9', label: 'Widen 21:9' },
  { key: 'pan_left', label: 'Pan left' },
  { key: 'pan_right', label: 'Pan right' },
];

export function LocationPlatePanel({ location, projectId }) {
  const queryClient = useQueryClient();
  // The newest reference with a generated image is what an unpicked scene
  // inherits, so that is the plate this panel represents.
  const { data: locRefs } = useQuery({
    queryKey: ['references', 'locations', location.id],
    queryFn: () => api.listReferences('locations', location.id),
  });
  const plateId = (locRefs || [])
    .filter((r) => r.asset_image_id)
    .slice(-1)[0]?.asset_image_id ?? null;
  const [showExpand, setShowExpand] = useState(false);
  const [expandJobId, setExpandJobId] = useState(null);
  const [angleIds, setAngleIds] = useState(null);

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

  // Multi-angle 360: one job → several AssetImages; poll them all as a set.
  const { data: angleAssets } = useQuery({
    queryKey: ['asset-images', 'angles', angleIds],
    queryFn: () => Promise.all(angleIds.map((id) => api.getAssetImage(id))),
    enabled: !!angleIds,
    refetchInterval: (q) => {
      const all = q.state.data;
      const settled = all && all.every((a) => a.status === 'completed' || a.status === 'failed');
      return settled ? false : 2000;
    },
  });
  const anglesRendering = !!angleIds && !(angleAssets || []).every(
    (a) => a.status === 'completed' || a.status === 'failed');
  const completedAngles = (angleAssets || []).filter((a) => a.status === 'completed' && a.image_url);

  const expand = useMutation({
    mutationFn: (preset) => api.expandPlate(location.id, { preset }),
    onSuccess: (r) => { setShowExpand(false); setExpandJobId(r.asset_image_id); },
  });
  const angles = useMutation({
    mutationFn: () => api.renderPlateAngles(location.id, {}),
    onSuccess: (r) => setAngleIds(r.asset_image_ids),
  });
  // Adding it to the library makes it the newest reference — and therefore the
  // default any scene without an explicit pick will use.
  const promote = useMutation({
    mutationFn: (assetImageId) => api.assignAssetImage('locations', location.id, assetImageId),
    onSuccess: () => {
      setExpandJobId(null);
      queryClient.invalidateQueries({ queryKey: ['references', 'locations', location.id] });
      invalidateProject();
    },
  });
  const regenAngle = useMutation({
    mutationFn: (assetImageId) => api.regeneratePlateAngle(assetImageId),
    // Re-render in place → resume polling the set (the row goes back to queued).
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['asset-images', 'angles', angleIds] }),
  });
  const deleteAngle = useMutation({
    mutationFn: (assetImageId) => api.deleteAssetImage(assetImageId),
    onSuccess: (_r, assetImageId) => setAngleIds((ids) => (ids || []).filter((i) => i !== assetImageId)),
  });
  const keepAll = useMutation({
    mutationFn: () => Promise.all(
      completedAngles.map((a) => api.assignAssetImage('locations', location.id, a.id))),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['references', 'locations', location.id] });
      setAngleIds(null);
    },
  });

  const busy = expanding || expand.isPending || promote.isPending
    || angles.isPending || anglesRendering;

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
              onClick={() => angles.mutate()}
              title="Render a 360 set of camera angles off this plate"
              className="flex items-center gap-1 h-5 px-1.5 rounded-frame border border-line text-[10px] text-fg-faint hover:text-fg hover:border-set transition-colors"
            >
              <Orbit className="w-3 h-3" /> Angles
            </button>
          </div>
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
              No images yet — generate one with (+) below. Each scene then picks
              which to use from its own “Primary for this scene”.
            </span>
          </div>
        )}
        {busy && (
          <div className="absolute inset-0 flex items-center justify-center gap-1.5 bg-bay-950/70 text-[11px] text-fg-muted">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> {anglesRendering ? 'Rendering angles…' : expanding ? 'Expanding…' : 'Saving…'}
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
              <Check className="w-3 h-3" /> Add to library
            </button>
          </div>
        </div>
      )}

      {/* Multi-angle 360 results: promote / regenerate / delete each; keep all
          adds the set to the asset library. */}
      {angleIds && (angleAssets || []).length > 0 && (
        <div className="mt-1.5">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] uppercase tracking-wide text-fg-faint">360 angles</span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => keepAll.mutate()}
                disabled={completedAngles.length === 0 || keepAll.isPending}
                title="Add all of these to the asset library"
                className="flex items-center gap-1 h-5 px-1.5 rounded-frame border border-lead-600 text-[10px] text-lead-400 hover:bg-lead-600/10 transition-colors disabled:opacity-40"
              >
                <Check className="w-3 h-3" /> Keep all
              </button>
              <button
                type="button"
                onClick={() => setAngleIds(null)}
                title="Discard these (does not delete the images)"
                className="h-5 px-1.5 rounded-frame border border-line text-[10px] text-fg-faint hover:text-fg transition-colors"
              >
                Dismiss
              </button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {(angleAssets || []).map((a) => {
              const isDone = a.status === 'completed' && a.image_url;
              const isFailed = a.status === 'failed';
              return (
                <div key={a.id} className="group relative aspect-video rounded-frame border border-line bg-bay-900 overflow-hidden">
                  {isDone ? (
                    <img src={api.getAssetImageFile(a.id)} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      {isFailed
                        ? <span className="text-[10px] text-stop">failed</span>
                        : <Loader2 className="w-3.5 h-3.5 animate-spin text-fg-faint" />}
                    </div>
                  )}
                  {/* Hover actions: regenerate + delete. */}
                  <div className="absolute top-0.5 right-0.5 flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      type="button"
                      onClick={() => regenAngle.mutate(a.id)}
                      title="Regenerate this angle"
                      className="w-4 h-4 rounded flex items-center justify-center bg-bay-950/70 text-fg-faint hover:text-fg"
                    >
                      <RefreshCw className="w-2.5 h-2.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteAngle.mutate(a.id)}
                      title="Delete this angle"
                      className="w-4 h-4 rounded flex items-center justify-center bg-bay-950/70 text-fg-faint hover:text-stop"
                    >
                      <Trash2 className="w-2.5 h-2.5" />
                    </button>
                  </div>
                  {/* Slot label + promote. */}
                  <div className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-bay-950/70 px-1 py-0.5">
                    <span className="text-[9px] text-fg-muted truncate">{a.params?.angle_slot || 'angle'}</span>
                    {isDone && (
                      <button
                        type="button"
                        onClick={() => promote.mutate(a.id)}
                        title="Use as plate"
                        className="text-[9px] text-set hover:text-set/80 shrink-0"
                      >
                        set plate
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {(expand.isError || promote.isError || angles.isError || expandFailed) && (
        <p className="text-[10px] text-stop mt-1.5">Plate operation failed.</p>
      )}
    </div>
  );
}
