import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ImageIcon, Plus, Star, Frame } from 'lucide-react';
import { api } from '../../lib/api';
import { SetImageDialog } from './SetImageDialog';

// Per-entity thumbnail grid of attached references, with a (+) to generate/
// assign a new one via the existing SetImageDialog flow. SetImageDialog's own
// mutations invalidate the ['references', pluralType, entityId] query, so this
// grid refreshes itself with no extra plumbing.
export function EntityAssetLibrary({ entityType, entityId, entityName, projectId, canonicalAssetImageId, plateAssetImageId }) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const pluralType = `${entityType}s`;
  const queryClient = useQueryClient();

  const { data: refs } = useQuery({
    queryKey: ['references', pluralType, entityId],
    queryFn: () => api.listReferences(pluralType, entityId),
  });

  const invalidateProject = () =>
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });

  // Setting the canonical ("hero") image feeds it into scene generation as an
  // identity reference (KAN-36). Characters only.
  const setCanonical = useMutation({
    mutationFn: (assetImageId) => api.setCanonicalImage(pluralType, entityId, assetImageId),
    onSuccess: invalidateProject,
  });
  // Setting the background plate — the fixed establishing background reused
  // across scenes here (KAN-41). Locations only.
  const setPlate = useMutation({
    mutationFn: (assetImageId) => api.setLocationPlate(entityId, assetImageId),
    onSuccess: invalidateProject,
  });

  const items = (refs || []).filter((r) => r.url || r.asset_image_id);

  return (
    <div className="mt-2.5 pt-2.5 border-t border-line/60">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] uppercase tracking-wide text-fg-faint">Library</span>
        <button
          type="button"
          onClick={() => setDialogOpen(true)}
          title="Generate or assign an image"
          className="flex items-center justify-center w-5 h-5 rounded border border-line text-fg-faint hover:text-fg hover:border-bay-600 transition-colors"
        >
          <Plus className="w-3 h-3" />
        </button>
      </div>

      {items.length === 0 ? (
        <p className="text-[11px] text-fg-faint">No images yet</p>
      ) : (
        <div className="grid grid-cols-3 gap-1.5">
          {items.map((ref) => {
            const thumb = api.getReferenceFileUrl(ref);
            const isCanonical = ref.asset_image_id && ref.asset_image_id === canonicalAssetImageId;
            const isPlate = ref.asset_image_id && ref.asset_image_id === plateAssetImageId;
            return (
              <div key={ref.id} className="group relative aspect-square rounded border border-line bg-bay-900 overflow-hidden">
                {thumb ? (
                  <img src={thumb} alt="" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <ImageIcon className="w-4 h-4 text-fg-faint" />
                  </div>
                )}
                {/* Characters: canonical identity image (KAN-36). */}
                {entityType === 'character' && ref.asset_image_id && (
                  <button
                    type="button"
                    onClick={() => setCanonical.mutate(isCanonical ? null : ref.asset_image_id)}
                    title={isCanonical ? 'Canonical identity image (click to unset)' : 'Set as canonical identity image'}
                    className={`absolute top-0.5 right-0.5 w-5 h-5 rounded flex items-center justify-center transition-opacity ${
                      isCanonical
                        ? 'text-lead-500 opacity-100'
                        : 'text-fg-faint opacity-0 group-hover:opacity-100 hover:text-lead-400'
                    }`}
                  >
                    <Star className={`w-3.5 h-3.5 ${isCanonical ? 'fill-lead-500' : ''}`} />
                  </button>
                )}
                {/* Locations: background plate (KAN-41). */}
                {entityType === 'location' && ref.asset_image_id && (
                  <button
                    type="button"
                    onClick={() => setPlate.mutate(isPlate ? null : ref.asset_image_id)}
                    title={isPlate ? 'Background plate (click to unset)' : 'Set as background plate'}
                    className={`absolute top-0.5 right-0.5 w-5 h-5 rounded flex items-center justify-center transition-opacity ${
                      isPlate
                        ? 'text-set opacity-100 bg-bay-950/60'
                        : 'text-fg-faint opacity-0 group-hover:opacity-100 hover:text-set bg-bay-950/40'
                    }`}
                  >
                    <Frame className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {dialogOpen && (
        <SetImageDialog
          entityType={entityType}
          entityId={entityId}
          entityName={entityName}
          projectId={projectId}
          open={dialogOpen}
          onOpenChange={setDialogOpen}
        />
      )}
    </div>
  );
}
