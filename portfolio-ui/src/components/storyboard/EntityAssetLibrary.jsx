import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ImageIcon, Plus } from 'lucide-react';
import { api } from '../../lib/api';
import { SetImageDialog } from './SetImageDialog';

// Per-entity thumbnail grid of attached references, with a (+) to generate/
// assign a new one via the existing SetImageDialog flow. SetImageDialog's own
// mutations invalidate the ['references', pluralType, entityId] query, so this
// grid refreshes itself with no extra plumbing.
//
// Browse-only by design. Choosing WHICH image an asset uses is a per-scene
// decision now — a character wears different clothes in different scenes — so
// it lives on the scene page's "Primary for this scene" picker
// (components/scene/ReferencePicker). There is deliberately no project-wide
// star here: a global pick would silently override every scene at once.
export function EntityAssetLibrary({ entityType, entityId, entityName, projectId }) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const pluralType = `${entityType}s`;

  const { data: refs } = useQuery({
    queryKey: ['references', pluralType, entityId],
    queryFn: () => api.listReferences(pluralType, entityId),
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
            return (
              <div key={ref.id} className="relative aspect-square rounded border border-line bg-bay-900 overflow-hidden">
                {thumb ? (
                  <img src={thumb} alt="" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <ImageIcon className="w-4 h-4 text-fg-faint" />
                  </div>
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
