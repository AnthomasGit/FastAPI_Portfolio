import { useState } from 'react';
import { Plus, X } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../lib/api';

// Storyboard-grid overview only: a thumbnail + name per linked asset, plus (+)
// add and unlink. Reference assignment and image generation live on the Scene
// Detail page — this cell is a read-mostly glance across the whole project.
const CONFIG = {
  characters: {
    singular: 'character', label: 'Character', itemsKey: 'characters', linksKey: 'character_links',
    list: api.listCharacters, create: api.createCharacter,
    ring: 'ring-emerald-500/40', text: 'text-emerald-300', addBtn: 'bg-emerald-600 hover:bg-emerald-500',
  },
  locations: {
    singular: 'location', label: 'Location', itemsKey: 'locations', linksKey: 'location_links',
    list: api.listLocations, create: api.createLocation,
    ring: 'ring-amber-500/40', text: 'text-amber-300', addBtn: 'bg-amber-600 hover:bg-amber-500',
  },
  props: {
    singular: 'prop', label: 'Prop', itemsKey: 'props', linksKey: 'prop_links',
    list: api.listProps, create: api.createProp,
    ring: 'ring-purple-500/40', text: 'text-purple-300', addBtn: 'bg-purple-600 hover:bg-purple-500',
  },
};

function AssetChip({ entity, cfg, link, onUnlink }) {
  const thumb = api.getLinkThumbUrl(link);
  return (
    <div className="group/chip flex items-center gap-1 pl-0.5 pr-1 py-0.5 rounded-full bg-white/5 border border-white/10">
      {thumb ? (
        <img src={thumb} alt="" className={`w-5 h-5 rounded-full object-cover ring-1 ${cfg.ring}`} />
      ) : (
        <span className="w-5 h-5 rounded-full bg-black/40 border border-white/10" />
      )}
      <span className={`text-[10px] truncate max-w-[70px] ${cfg.text}`}>{entity.name}</span>
      <button
        onClick={onUnlink}
        title="Remove from scene"
        className="opacity-0 group-hover/chip:opacity-100 p-0.5 rounded text-slate-500 hover:text-red-400 transition-all focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-red-400 focus-visible:opacity-100"
      >
        <X className="w-2.5 h-2.5" />
      </button>
    </div>
  );
}

export function SceneAssetCell({ scene, projectId, entityType }) {
  const cfg = CONFIG[entityType];
  const queryClient = useQueryClient();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [newName, setNewName] = useState('');

  const linked = scene[cfg.itemsKey] || [];
  const links = scene[cfg.linksKey] || [];
  const linkByEntity = Object.fromEntries(links.map((l) => [l.entity_id, l]));
  const linkedIds = new Set(linked.map((e) => e.id));

  const invalidateProject = () =>
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });

  const { data: allEntities = [] } = useQuery({
    queryKey: [entityType, projectId],
    queryFn: () => cfg.list(projectId),
    enabled: pickerOpen,
  });
  const available = allEntities.filter((e) => !linkedIds.has(e.id));

  const linkMut = useMutation({
    mutationFn: (entityId) => api.linkSceneEntity(scene.id, entityType, entityId),
    onSuccess: invalidateProject,
  });
  const unlinkMut = useMutation({
    mutationFn: (entityId) => api.unlinkSceneEntity(scene.id, entityType, entityId),
    onSuccess: invalidateProject,
  });
  const createMut = useMutation({
    mutationFn: (name) => cfg.create(projectId, { name }),
    onSuccess: async (created) => {
      await api.linkSceneEntity(scene.id, entityType, created.id);
      setNewName('');
      queryClient.invalidateQueries({ queryKey: [entityType, projectId] });
      invalidateProject();
    },
  });

  return (
    <div className="flex flex-wrap gap-1 min-h-[28px] items-start">
      {linked.map((e) => (
        <AssetChip
          key={e.id}
          entity={e}
          cfg={cfg}
          link={linkByEntity[e.id]}
          onUnlink={() => unlinkMut.mutate(e.id)}
        />
      ))}

      <div className="relative">
        <button
          onClick={() => setPickerOpen((v) => !v)}
          className="w-5 h-5 rounded-full bg-white/10 flex items-center justify-center hover:bg-white/20 transition-colors shrink-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40"
          title={`Add ${cfg.label.toLowerCase()}`}
        >
          <Plus className="w-3 h-3 text-slate-400" />
        </button>

        {pickerOpen && (
          <div className="absolute z-20 top-6 left-0 w-52 rounded-lg border border-white/10 bg-slate-900 p-2 space-y-2 shadow-xl">
            <div className="flex flex-wrap gap-1">
              {available.length === 0 && (
                <p className="text-[10px] text-slate-500">None available — create below.</p>
              )}
              {available.map((e) => (
                <button
                  key={e.id}
                  onClick={() => linkMut.mutate(e.id)}
                  disabled={linkMut.isPending}
                  className="text-[10px] px-1.5 py-0.5 rounded border border-white/10 text-slate-300 hover:bg-white/10 transition-colors disabled:opacity-40"
                >
                  + {e.name}
                </button>
              ))}
            </div>
            <div className="flex gap-1 pt-2 border-t border-white/10">
              <input
                className="flex-1 min-w-0 bg-black/40 border border-white/10 rounded px-1.5 py-0.5 text-[11px] text-white focus:outline-none focus:border-white/30"
                placeholder={`New ${cfg.label.toLowerCase()}...`}
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && newName.trim()) createMut.mutate(newName.trim()); }}
              />
              <button
                onClick={() => newName.trim() && createMut.mutate(newName.trim())}
                disabled={createMut.isPending || !newName.trim()}
                className={`px-2 py-0.5 rounded text-[11px] text-white disabled:opacity-40 ${cfg.addBtn}`}
              >
                Add
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
