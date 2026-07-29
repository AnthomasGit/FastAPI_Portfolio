import { useState } from 'react';
import { Plus, ImageIcon, X, Images } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../lib/api';
import { ReferenceManager } from '../storyboard/ReferenceManager';
import { SetImageDialog } from '../storyboard/SetImageDialog';
import { ReferencePicker } from './ReferencePicker';

// entityType is plural — matches API paths, SceneResponse link keys, and the
// scene items array key.
const CONFIG = {
  characters: {
    singular: 'character', label: 'Character', itemsKey: 'characters', linksKey: 'character_links',
    list: api.listCharacters, create: api.createCharacter,
    accent: 'emerald', ring: 'ring-emerald-500/40', text: 'text-emerald-300',
    addBtn: 'bg-emerald-600 hover:bg-emerald-500',
  },
  props: {
    singular: 'prop', label: 'Prop', itemsKey: 'props', linksKey: 'prop_links',
    list: api.listProps, create: api.createProp,
    accent: 'purple', ring: 'ring-purple-500/40', text: 'text-purple-300',
    addBtn: 'bg-purple-600 hover:bg-purple-500',
  },
  locations: {
    singular: 'location', label: 'Location', itemsKey: 'locations', linksKey: 'location_links',
    list: api.listLocations, create: api.createLocation,
    accent: 'amber', ring: 'ring-amber-500/40', text: 'text-amber-300',
    addBtn: 'bg-amber-600 hover:bg-amber-500',
  },
};

function AssetCard({ entity, entityType, cfg, link, onSetReference, onUnlink, onManageRefs, onSetImage }) {
  const { data: refs = [] } = useQuery({
    queryKey: ['references', entityType, entity.id],
    queryFn: () => api.listReferences(entityType, entity.id),
  });
  const thumb = api.getLinkThumbUrl(link);
  const selected = link?.reference_id || '';

  return (
    <div className={`w-40 shrink-0 rounded-lg border border-white/10 bg-black/40 overflow-hidden ${thumb ? `ring-1 ${cfg.ring}` : ''}`}>
      <div className="aspect-square bg-black/50 flex items-center justify-center relative">
        {thumb ? (
          <img src={thumb} alt={entity.name} className="w-full h-full object-cover" />
        ) : (
          <ImageIcon className="w-6 h-6 text-slate-700" />
        )}
        <button
          onClick={onUnlink}
          title="Remove from scene"
          className="absolute top-1 right-1 p-0.5 rounded bg-black/60 text-slate-400 hover:text-red-400 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-red-400"
        >
          <X className="w-3 h-3" />
        </button>
      </div>
      <div className="p-2 space-y-1.5">
        <p className={`text-xs font-medium truncate ${cfg.text}`}>{entity.name}</p>
        <div className="flex items-center gap-1">
          <ReferencePicker
            refs={refs}
            selectedId={selected || null}
            onSelect={onSetReference}
            ring={cfg.ring}
          />
          <button
            onClick={onManageRefs}
            title="Manage references"
            className="p-1 rounded hover:bg-white/10 text-slate-500 hover:text-slate-300 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/30"
          >
            <Images className="w-3 h-3" />
          </button>
          <button
            onClick={onSetImage}
            title="Generate / set image"
            className="p-1 rounded hover:bg-white/10 text-slate-500 hover:text-cyan-400 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400"
          >
            <ImageIcon className="w-3 h-3" />
          </button>
        </div>
      </div>
    </div>
  );
}

export function SceneAssetSection({ scene, projectId, entityType }) {
  const cfg = CONFIG[entityType];
  const queryClient = useQueryClient();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [refTarget, setRefTarget] = useState(null);
  const [imageTarget, setImageTarget] = useState(null);

  const linked = scene[cfg.itemsKey] || [];
  const links = scene[cfg.linksKey] || [];
  const linkByEntity = Object.fromEntries(links.map((l) => [l.entity_id, l]));
  const linkedIds = new Set(linked.map((e) => e.id));

  const invalidateScene = () => {
    queryClient.invalidateQueries({ queryKey: ['scene', scene.id] });
    // ReferenceManager and SetImageDialog mutate references outside React
    // Query (they own their own local list), so we also drop the per-entity
    // references cache — otherwise a freshly-uploaded/generated reference
    // won't show up in the ReferencePicker for any linked asset until reload.
    queryClient.invalidateQueries({ queryKey: ['references', entityType] });
  };

  const { data: allEntities = [] } = useQuery({
    queryKey: [entityType, projectId],
    queryFn: () => cfg.list(projectId),
    enabled: pickerOpen,
  });
  const available = allEntities.filter((e) => !linkedIds.has(e.id));

  const linkMut = useMutation({
    mutationFn: (entityId) => api.linkSceneEntity(scene.id, entityType, entityId),
    onSuccess: invalidateScene,
  });
  const unlinkMut = useMutation({
    mutationFn: (entityId) => api.unlinkSceneEntity(scene.id, entityType, entityId),
    onSuccess: invalidateScene,
  });
  const setRefMut = useMutation({
    mutationFn: ({ entityId, referenceId }) =>
      api.setSceneEntityReference(scene.id, entityType, entityId, referenceId),
    onSuccess: invalidateScene,
  });
  const createMut = useMutation({
    mutationFn: (name) => cfg.create(projectId, { name }),
    onSuccess: async (created) => {
      await api.linkSceneEntity(scene.id, entityType, created.id);
      setNewName('');
      queryClient.invalidateQueries({ queryKey: [entityType, projectId] });
      invalidateScene();
    },
  });

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-3">
        <h2 className={`text-lg font-semibold ${cfg.text}`}>{cfg.label}s</h2>
        <button
          onClick={() => setPickerOpen(true)}
          className="w-5 h-5 rounded-full bg-white/10 flex items-center justify-center hover:bg-white/20 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40"
          title={`Add ${cfg.label.toLowerCase()}`}
        >
          <Plus className="w-3 h-3 text-slate-300" />
        </button>
      </div>

      {linked.length === 0 ? (
        <p className="text-xs text-slate-600">No {cfg.label.toLowerCase()}s in this scene yet.</p>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {linked.map((e) => (
            <AssetCard
              key={e.id}
              entity={e}
              entityType={entityType}
              cfg={cfg}
              link={linkByEntity[e.id]}
              onSetReference={(referenceId) => setRefMut.mutate({ entityId: e.id, referenceId })}
              onUnlink={() => unlinkMut.mutate(e.id)}
              onManageRefs={() => setRefTarget(e)}
              onSetImage={() => setImageTarget(e)}
            />
          ))}
        </div>
      )}

      {pickerOpen && (
        <div className="rounded-lg border border-white/10 bg-black/40 p-3 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400">Add existing {cfg.label.toLowerCase()}</p>
            <button onClick={() => setPickerOpen(false)} className="text-slate-500 hover:text-slate-300">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {available.length === 0 && (
              <p className="text-xs text-slate-600">None available — create one below.</p>
            )}
            {available.map((e) => (
              <button
                key={e.id}
                onClick={() => linkMut.mutate(e.id)}
                disabled={linkMut.isPending}
                className={`text-[11px] px-2 py-1 rounded border border-white/10 text-slate-300 hover:bg-white/10 transition-colors disabled:opacity-40`}
              >
                + {e.name}
              </button>
            ))}
          </div>
          <div className="flex gap-2 pt-2 border-t border-white/10">
            <input
              className="flex-1 bg-black/50 border border-white/10 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-white/30"
              placeholder={`New ${cfg.label.toLowerCase()} name...`}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && newName.trim()) createMut.mutate(newName.trim()); }}
            />
            <button
              onClick={() => newName.trim() && createMut.mutate(newName.trim())}
              disabled={createMut.isPending || !newName.trim()}
              className={`px-3 py-1 rounded text-xs text-white disabled:opacity-40 ${cfg.addBtn}`}
            >
              Create
            </button>
          </div>
        </div>
      )}

      {refTarget && (
        <ReferenceManager
          entityType={cfg.singular}
          entityId={refTarget.id}
          entityName={refTarget.name}
          open={!!refTarget}
          onOpenChange={(v) => { if (!v) { setRefTarget(null); invalidateScene(); } }}
        />
      )}
      {imageTarget && (
        <SetImageDialog
          entityType={cfg.singular}
          entityId={imageTarget.id}
          entityName={imageTarget.name}
          projectId={projectId}
          open={!!imageTarget}
          onOpenChange={(v) => { if (!v) { setImageTarget(null); invalidateScene(); } }}
          onAssigned={(referenceId) =>
            setRefMut.mutate({ entityId: imageTarget.id, referenceId })
          }
        />
      )}
    </section>
  );
}
