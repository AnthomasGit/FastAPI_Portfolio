import { useQuery } from '@tanstack/react-query';
import { ImageIcon } from 'lucide-react';
import { api } from '../../lib/api';

// All material of one entity type across the whole project: generated asset
// images (via listAssetImages) plus uploaded-only references (via
// listProjectReferences). The two sets are disjoint — a Reference created
// from a generated image carries asset_image_id and is excluded here so it
// isn't shown twice.
export function PooledAssetGallery({ entityType, projectId }) {
  const { data: assetImages } = useQuery({
    queryKey: ['asset-images', entityType, projectId],
    queryFn: () => api.listAssetImages({ entity_type: entityType, project_id: projectId }),
  });

  const { data: projectRefs } = useQuery({
    queryKey: ['project-references', entityType, projectId],
    queryFn: () => api.listProjectReferences(projectId, entityType),
  });

  const generated = (assetImages || []).filter((a) => a.status === 'completed');
  const uploaded = (projectRefs || []).filter((r) => r.url && !r.asset_image_id);

  if (generated.length === 0 && uploaded.length === 0) return null;

  return (
    <section className="rounded-frame border border-line bg-bay-850 mb-3">
      <header className="flex items-center gap-2 px-4 py-2.5 border-b border-line">
        <h3 className="text-xs font-semibold text-fg-muted uppercase tracking-wide">All material</h3>
        <span className="font-mono text-[11px] text-fg-faint">{generated.length + uploaded.length}</span>
      </header>
      <div className="p-3">
        <div className="grid grid-cols-4 sm:grid-cols-6 lg:grid-cols-8 gap-1.5">
          {generated.map((a) => (
            <div key={a.id} className="aspect-square rounded border border-line bg-bay-900 overflow-hidden">
              <img src={api.getAssetImageFile(a.id)} alt="" className="w-full h-full object-cover" />
            </div>
          ))}
          {uploaded.map((ref) => {
            const thumb = api.getReferenceFileUrl(ref);
            return (
              <div key={ref.id} className="aspect-square rounded border border-line bg-bay-900 overflow-hidden">
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
      </div>
    </section>
  );
}
