import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Loader2, AlertTriangle, RefreshCw, Plus } from 'lucide-react';
import { useStagingStore } from '@/stores/stagingStore';

const STATUS_CONFIG = {
  queued: { label: 'Queued', variant: 'outline' },
  mesh_processing: { label: 'Processing', variant: 'secondary' },
  mesh_ready: { label: 'Ready', variant: 'default' },
  mesh_failed: { label: 'Failed', variant: 'destructive' },
  rig_queued: { label: 'Rig Queued', variant: 'secondary' },
  rig_processing: { label: 'Rig Processing', variant: 'secondary' },
  rigged: { label: 'Rigged', variant: 'default' },
  rig_failed: { label: 'Rig Failed', variant: 'destructive' },
};

function StatusChip({ status }) {
  const config = STATUS_CONFIG[status] || { label: status, variant: 'outline' };
  return <Badge variant={config.variant}>{config.label}</Badge>;
}

export function AssetDrawer({ projectId, characters, props }) {
  const queryClient = useQueryClient();
  const [showRefPicker, setShowRefPicker] = useState(null);

  const { data: assets, isLoading } = useQuery({
    queryKey: ['assets3d', projectId],
    queryFn: () => api.listAssets3D(projectId),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const hasActive = data.some(a =>
        ['queued', 'mesh_processing', 'rig_queued', 'rig_processing'].includes(a.status)
      );
      return hasActive ? 3000 : false;
    },
  });

  const generateMutation = useMutation({
    mutationFn: (data) => api.generateAsset3D(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assets3d', projectId] });
      setShowRefPicker(null);
    },
  });

  const addPlacement = useStagingStore((s) => s.addPlacement);

  const retryMutation = useMutation({
    mutationFn: (id) => api.retryAsset3D(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assets3d', projectId] });
    },
  });

  const [selectedEntity, setSelectedEntity] = useState(null);
  const [userRefOverride, setUserRefOverride] = useState(null);

  const { data: references } = useQuery({
    queryKey: ['references', selectedEntity?.entity_type, selectedEntity?.id],
    queryFn: () => selectedEntity
      ? api.listReferences(
          selectedEntity.entity_type === 'character' ? 'characters' : 'props',
          selectedEntity.id
        )
      : Promise.resolve([]),
    enabled: !!selectedEntity,
  });

  const defaultRef = useMemo(() => {
    if (!references || references.length === 0) return null;
    const byRole = {};
    references.forEach(r => { byRole[r.role] = r; });
    return byRole['tpose']
      || references.find(r => r.url && !r.asset_image_id && r.role !== 'primary')
      || byRole['primary']
      || references[0];
  }, [references]);

  const selectedRef = userRefOverride ?? defaultRef?.id ?? null;
  const activeRef = references?.find(r => r.id === selectedRef) || null;
  const refWarning = activeRef?.asset_image_id
    ? 'Generated image — mesh quality may suffer; prefer a T-pose photo'
    : null;

  if (isLoading) {
    return (
      <div className="flex justify-center p-8">
        <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
      </div>
    );
  }

  const assetMap = {};
  if (assets) {
    assets.forEach(a => {
      if (!assetMap[a.entity_id]) assetMap[a.entity_id] = [];
      assetMap[a.entity_id].push(a);
    });
  }

  const entities = [
    ...(characters || []).map(c => ({ ...c, entity_type: 'character' })),
    ...(props || []).map(p => ({ ...p, entity_type: 'prop' })),
  ];

  return (
    <div className="space-y-4">
      {entities.length === 0 && (
        <p className="text-slate-500 text-sm">No characters or props yet. Create some first.</p>
      )}

      {entities.map((entity) => {
        const entityAssets = assetMap[entity.id] || [];
        const latest = entityAssets.length > 0 ? entityAssets[0] : null;
        const isProcessing = latest && ['queued', 'mesh_processing', 'rig_queued', 'rig_processing'].includes(latest.status);

        return (
          <div key={entity.id} className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-4">
            <div className="flex items-center justify-between mb-2">
              <div>
                <span className={`font-medium ${entity.entity_type === 'character' ? 'text-emerald-300' : 'text-purple-300'}`}>
                  {entity.name}
                </span>
                <span className="text-xs text-slate-500 ml-2 capitalize">({entity.entity_type})</span>
              </div>
              <div className="flex items-center gap-2">
                {latest && <StatusChip status={latest.status} />}
                {!isProcessing && (
                  <Button
                    size="xs"
                    variant="outline"
                    onClick={() => {
                      setSelectedEntity(entity);
                      setUserRefOverride(null);
                      setShowRefPicker(entity.id);
                    }}
                    className="border-blue-500/30 text-blue-400 hover:text-blue-300"
                  >
                    Generate 3D
                  </Button>
                )}
              </div>
            </div>

            {latest?.error && (
              <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 rounded-lg px-3 py-2 mb-2">
                <AlertTriangle className="w-3 h-3 shrink-0" />
                <span>{latest.error}</span>
              </div>
            )}

            {latest?.status === 'mesh_failed' && (
              <div className="flex gap-2">
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => retryMutation.mutate(latest.id)}
                  disabled={retryMutation.isPending}
                  className="border-amber-500/30 text-amber-400"
                >
                  {retryMutation.isPending ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <RefreshCw className="w-3 h-3" />
                  )}
                  Retry
                </Button>
              </div>
            )}

            {entityAssets.length > 1 && (
              <details className="mt-2">
                <summary className="text-xs text-slate-500 cursor-pointer hover:text-slate-300">
                  History ({entityAssets.length} attempts)
                </summary>
                <div className="mt-2 space-y-1">
                  {entityAssets.map((a) => (
                    <div key={a.id} className="flex items-center justify-between text-xs text-slate-400 bg-black/20 rounded-lg px-3 py-1.5">
                      <span>{new Date(a.created_at).toLocaleString()}</span>
                      <StatusChip status={a.status} />
                      {(a.status === 'mesh_ready' || a.status === 'rigged') && (
                        <div className="flex items-center gap-2">
                          <a
                            href={api.getAsset3DFile(a.id)}
                            download
                            className="text-blue-400 hover:text-blue-300 underline text-[10px]"
                          >
                            Download GLB
                          </a>
                          <button
                            onClick={() => addPlacement(a.id)}
                            className="flex items-center gap-0.5 text-[10px] text-emerald-400 hover:text-emerald-300 transition-colors"
                          >
                            <Plus className="w-3 h-3" />
                            Add to Scene
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        );
      })}

      {showRefPicker && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowRefPicker(null)}>
          <div className="bg-slate-900 border border-white/10 rounded-2xl p-6 max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-4">Select Reference Image</h3>
            <p className="text-sm text-slate-400 mb-4">
              Choose a reference photo for mesh generation. For best results, use a front-facing T-pose photo with an uncluttered background.
            </p>

            <div className="mb-4">
              <label className="text-xs text-slate-500 mb-1 block">Entity</label>
              <select
                className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-200"
                value={selectedEntity?.id || ''}
                onChange={(e) => {
                  const ent = entities.find(x => x.id === e.target.value);
                  setSelectedEntity(ent);
                  setUserRefOverride(null);
                }}
              >
                {entities.map((e) => (
                  <option key={e.id} value={e.id}>{e.name} ({e.entity_type})</option>
                ))}
              </select>
            </div>

            {references && references.length > 0 && (
              <div className="mb-4">
                <label className="text-xs text-slate-500 mb-1 block">Reference Image</label>
                <select
                  className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-200"
                  value={selectedRef || ''}
                  onChange={(e) => {
                    setUserRefOverride(e.target.value);
                  }}
                >
                  {references.map((ref) => (
                    <option key={ref.id} value={ref.id}>
                      {ref.role} — {ref.url || ref.processed_url || 'no file'}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {!references || references.length === 0 ? (
              <p className="text-xs text-amber-400 mb-4">No references found. Upload one first in the References tab.</p>
            ) : null}

            {refWarning && (
              <div className="flex items-center gap-2 text-xs text-amber-400 bg-amber-500/10 rounded-lg px-3 py-2 mb-4">
                <AlertTriangle className="w-3 h-3 shrink-0" />
                <span>{refWarning}</span>
              </div>
            )}

            {generateMutation.isError && (
              <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 rounded-lg px-3 py-2 mb-4">
                <AlertTriangle className="w-3 h-3 shrink-0" />
                <span>{generateMutation.error?.message || 'Generation failed. Check console for details.'}</span>
              </div>
            )}

            <div className="flex gap-2 justify-end">
              <Button variant="outline" size="sm" onClick={() => setShowRefPicker(null)}>
                Cancel
              </Button>
              <Button
                size="sm"
                disabled={!selectedRef || generateMutation.isPending || !references || references.length === 0}
                onClick={() => {
                  if (!selectedEntity || !selectedRef) return;
                  const entityType = selectedEntity.entity_type;
                  generateMutation.mutate({
                    entity_type: entityType,
                    entity_id: selectedEntity.id,
                    reference_id: selectedRef,
                  });
                }}
                className="bg-gradient-to-r from-blue-600 to-cyan-500 text-white"
              >
                {generateMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  'Generate'
                )}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
