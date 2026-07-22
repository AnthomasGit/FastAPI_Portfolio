import { useState } from 'react';
import { Plus, ImageIcon, X } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Badge } from '../ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '../ui/dialog';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { api } from '../../lib/api';
import { ReferenceManager } from './ReferenceManager';
import { SetImageDialog } from './SetImageDialog';

// entityType is the plural form — it matches the API path segment
// (/links/characters/…), the SceneResponse links field (character_links), the
// listReferences path, and the scene items array key (scene.characters).
const CONFIG = {
  characters: {
    singular: 'character', label: 'Character',
    itemsKey: 'characters', linksKey: 'character_links',
    list: api.listCharacters, create: api.createCharacter,
    badge: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20 hover:bg-emerald-500/20',
    addBtn: 'bg-emerald-600 hover:bg-emerald-500',
  },
  locations: {
    singular: 'location', label: 'Location',
    itemsKey: 'locations', linksKey: 'location_links',
    list: api.listLocations, create: api.createLocation,
    badge: 'bg-amber-500/10 text-amber-300 border-amber-500/20 hover:bg-amber-500/20',
    addBtn: 'bg-amber-600 hover:bg-amber-500',
  },
  props: {
    singular: 'prop', label: 'Prop',
    itemsKey: 'props', linksKey: 'prop_links',
    list: api.listProps, create: api.createProp,
    badge: 'bg-purple-500/10 text-purple-300 border-purple-500/20 hover:bg-purple-500/20',
    addBtn: 'bg-purple-600 hover:bg-purple-500',
  },
};

function LinkedAssetBadge({ entity, entityType, cfg, link, onSetReference, onUnlink, onManageRefs, onSetImage }) {
  const { data: refs = [] } = useQuery({
    queryKey: ['references', entityType, entity.id],
    queryFn: () => api.listReferences(entityType, entity.id),
  });
  const selected = link?.reference_id || '';

  return (
    <div className="flex items-center gap-0.5">
      <button onClick={onManageRefs} className="focus:outline-none" title="Manage references">
        <Badge variant="secondary" className={`text-[10px] cursor-pointer transition-colors ${cfg.badge}`}>
          {entity.name}
        </Badge>
      </button>
      {refs.length > 0 && (
        <select
          value={selected}
          onChange={(e) => onSetReference(e.target.value || null)}
          title="Reference used in this scene"
          className="text-[10px] bg-black/40 border border-white/10 rounded text-slate-300 max-w-[80px] py-0.5"
        >
          <option value="">— ref —</option>
          {refs.map((r) => (
            <option key={r.id} value={r.id}>{r.role}</option>
          ))}
        </select>
      )}
      <button
        onClick={onSetImage}
        className="p-0.5 rounded hover:bg-white/10 text-slate-500 hover:text-cyan-400 transition-colors"
        title="Set image"
      >
        <ImageIcon className="w-3 h-3" />
      </button>
      <button
        onClick={onUnlink}
        className="p-0.5 rounded hover:bg-white/10 text-slate-500 hover:text-red-400 transition-colors"
        title="Remove from scene"
      >
        <X className="w-3 h-3" />
      </button>
    </div>
  );
}

export function SceneAssetCell({ scene, projectId, entityType }) {
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

  const invalidateProject = () =>
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });

  // Existing project entities for the picker (only fetched while the dialog is open).
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
  const setRefMut = useMutation({
    mutationFn: ({ entityId, referenceId }) =>
      api.setSceneEntityReference(scene.id, entityType, entityId, referenceId),
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
    <div className="flex flex-wrap gap-1.5 min-h-[32px] items-start">
      {linked.map((e) => (
        <LinkedAssetBadge
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

      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogTrigger asChild>
          <button
            className="w-5 h-5 rounded-full bg-white/10 flex items-center justify-center hover:bg-white/20 transition-colors shrink-0"
            title={`Add ${cfg.label.toLowerCase()}`}
          >
            <Plus className="w-3 h-3 text-slate-400" />
          </button>
        </DialogTrigger>
        <DialogContent className="bg-slate-900 border-white/10 text-slate-200">
          <DialogHeader>
            <DialogTitle>Add {cfg.label} to Scene</DialogTitle>
          </DialogHeader>

          <div className="space-y-3">
            <div>
              <p className="text-xs text-slate-400 mb-1.5">Existing {cfg.label.toLowerCase()}s</p>
              <div className="flex flex-wrap gap-1.5">
                {available.length === 0 && (
                  <p className="text-xs text-slate-500">
                    None available — create one below.
                  </p>
                )}
                {available.map((e) => (
                  <button
                    key={e.id}
                    onClick={() => linkMut.mutate(e.id)}
                    disabled={linkMut.isPending}
                    className={`text-[11px] px-2 py-1 rounded border transition-colors disabled:opacity-40 ${cfg.badge}`}
                  >
                    + {e.name}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex gap-2 pt-2 border-t border-white/10">
              <Input
                className="bg-black/40 border-white/10 text-white"
                placeholder={`New ${cfg.label.toLowerCase()} name...`}
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && newName.trim()) createMut.mutate(newName.trim());
                }}
              />
              <Button
                onClick={() => newName.trim() && createMut.mutate(newName.trim())}
                disabled={createMut.isPending || !newName.trim()}
                className={cfg.addBtn}
              >
                Create
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {refTarget && (
        <ReferenceManager
          entityType={cfg.singular}
          entityId={refTarget.id}
          entityName={refTarget.name}
          open={!!refTarget}
          onOpenChange={(v) => { if (!v) setRefTarget(null); }}
        />
      )}
      {imageTarget && (
        <SetImageDialog
          entityType={cfg.singular}
          entityId={imageTarget.id}
          entityName={imageTarget.name}
          projectId={projectId}
          open={!!imageTarget}
          onOpenChange={(v) => { if (!v) setImageTarget(null); }}
        />
      )}
    </div>
  );
}
