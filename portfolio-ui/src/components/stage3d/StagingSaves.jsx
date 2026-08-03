import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Save, Trash2, ChevronDown, FilePlus2 } from 'lucide-react';
import { api } from '@/lib/api';
import { useStagingStore } from '@/stores/stagingStore';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu';
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from '@/components/ui/popover';

export function StagingSaves({ sceneId }) {
  const [name, setName] = useState('');
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveMode, setSaveMode] = useState('menu'); // 'menu' | 'new'
  const [loadedSave, setLoadedSave] = useState(null); // {id, name} | null
  const queryClient = useQueryClient();
  const getUpdatePayload = useStagingStore((s) => s.getUpdatePayload);
  const hydrateFromServer = useStagingStore((s) => s.hydrateFromServer);

  const { data: saves } = useQuery({
    queryKey: ['staging-saves', sceneId],
    queryFn: () => api.listStagingSaves(sceneId),
    enabled: !!sceneId,
  });

  // Flush the current editor state before snapshotting so a save never
  // misses edits still waiting on the autosave debounce
  const flushStaging = async () => {
    const staging = await api.putStaging(sceneId, getUpdatePayload());
    queryClient.setQueryData(['staging', sceneId], staging);
  };

  const closeSavePopover = () => {
    setSaveOpen(false);
    setSaveMode('menu');
    setName('');
  };

  const createMutation = useMutation({
    mutationFn: async (saveName) => {
      await flushStaging();
      return api.createStagingSave(sceneId, saveName);
    },
    onSuccess: (save) => {
      setLoadedSave({ id: save.id, name: save.name });
      closeSavePopover();
      queryClient.invalidateQueries({ queryKey: ['staging-saves', sceneId] });
    },
  });

  const overwriteMutation = useMutation({
    mutationFn: async (save) => {
      await flushStaging();
      return api.updateStagingSave(save.id);
    },
    onSuccess: (_, save) => {
      // The overwritten save now holds the current stage — it becomes the slot.
      setLoadedSave({ id: save.id, name: save.name });
      closeSavePopover();
      queryClient.invalidateQueries({ queryKey: ['staging-saves', sceneId] });
    },
  });

  const restoreMutation = useMutation({
    mutationFn: (save) => api.restoreStagingSave(save.id),
    onSuccess: (staging, save) => {
      queryClient.setQueryData(['staging', sceneId], staging);
      hydrateFromServer(staging);
      setLoadedSave({ id: save.id, name: save.name });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (saveId) => api.deleteStagingSave(saveId),
    onSuccess: (_, saveId) => {
      if (loadedSave?.id === saveId) setLoadedSave(null);
      queryClient.invalidateQueries({ queryKey: ['staging-saves', sceneId] });
    },
  });

  const submitNewSave = (e) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || createMutation.isPending) return;
    createMutation.mutate(trimmed);
  };

  const onSaveOpenChange = (open) => {
    setSaveOpen(open);
    if (!open) {
      setSaveMode('menu');
      setName('');
    }
  };

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs font-semibold text-fg-muted uppercase tracking-wider">
        Stage:
      </span>
      <span
        className={`text-xs truncate max-w-[140px] ${
          loadedSave ? 'text-lead-500' : 'text-fg-faint italic'
        }`}
        title={loadedSave ? loadedSave.name : 'No stage loaded'}
      >
        {loadedSave ? loadedSave.name : 'none'}
      </span>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="xs"
            variant="outline"
            disabled={restoreMutation.isPending}
            className="border-line text-fg hover:text-fg"
            title="Load a saved stage"
          >
            {restoreMutation.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5 mr-1" />
            )}
            Load
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="center"
          className="bg-bay-850 border-line min-w-[14rem]"
        >
          {!saves || saves.length === 0 ? (
            <DropdownMenuItem disabled className="text-fg-muted text-xs">
              No saved stages yet
            </DropdownMenuItem>
          ) : (
            saves.map((save) => (
              <DropdownMenuItem
                key={save.id}
                disabled={restoreMutation.isPending || deleteMutation.isPending}
                onSelect={() => restoreMutation.mutate(save)}
                className="text-fg focus:bg-lead-500/40 focus:text-bay-950 gap-2"
                title="Restore this stage"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-xs truncate">
                    {save.name}
                    {loadedSave?.id === save.id && (
                      <span className="text-lead-500 ml-1.5">(loaded)</span>
                    )}
                  </p>
                  <p className="text-[10px] text-fg-muted">
                    {new Date(save.created_at).toLocaleString()}
                  </p>
                </div>
                <button
                  type="button"
                  title="Delete this save"
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteMutation.mutate(save.id);
                  }}
                  className="p-1 rounded text-fg-muted hover:text-stop hover:bg-stop/15 shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </DropdownMenuItem>
            ))
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <div className="w-px h-5 bg-bay-700" />

      <Popover open={saveOpen} onOpenChange={onSaveOpenChange}>
        <PopoverTrigger asChild>
          <Button
            size="xs"
            variant="outline"
            className="border-line text-fg hover:text-fg"
            title="Save the current stage"
          >
            <Save className="w-3.5 h-3.5 mr-1" />
            Save
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="center"
          className="bg-bay-850 border-line w-64 p-3"
        >
          {saveMode === 'menu' ? (
            <div className="space-y-2">
              <p className="text-[10px] text-fg-muted truncate">
                {loadedSave ? (
                  <>Loaded: <span className="text-fg">{loadedSave.name}</span></>
                ) : (
                  'No stage loaded'
                )}
              </p>
              <button
                type="button"
                disabled={!loadedSave || overwriteMutation.isPending}
                onClick={() => overwriteMutation.mutate(loadedSave)}
                title={
                  loadedSave
                    ? `Overwrite "${loadedSave.name}" with the current stage`
                    : 'Load or create a save first'
                }
                className="w-full flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium bg-lead-500/40 text-lead-500 border border-lead-500 hover:bg-lead-400/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {overwriteMutation.isPending ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Save className="w-3.5 h-3.5" />
                )}
                Save
              </button>
              <button
                type="button"
                onClick={() => setSaveMode('new')}
                className="w-full flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium bg-bay-800 text-fg border border-line hover:bg-bay-700 hover:text-fg transition-colors"
              >
                <FilePlus2 className="w-3.5 h-3.5" />
                New
              </button>
              <button
                type="button"
                disabled={!saves || saves.length === 0}
                onClick={() => setSaveMode('overwrite')}
                title="Overwrite a specific save with the current stage"
                className="w-full flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium bg-bay-800 text-fg border border-line hover:bg-bay-700 hover:text-fg disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <Save className="w-3.5 h-3.5" />
                Overwrite…
              </button>
              {overwriteMutation.isError && (
                <p className="text-[10px] text-stop">
                  {overwriteMutation.error.message}
                </p>
              )}
            </div>
          ) : saveMode === 'overwrite' ? (
            <div className="space-y-1.5">
              <p className="text-[10px] text-fg-muted">
                Overwrite which save with the current stage?
              </p>
              <div className="max-h-56 overflow-y-auto space-y-1">
                {(saves || []).map((save) => (
                  <button
                    key={save.id}
                    type="button"
                    disabled={overwriteMutation.isPending}
                    onClick={() => overwriteMutation.mutate(save)}
                    className="w-full text-left px-2 py-1.5 rounded bg-bay-800 border border-line hover:bg-lead-400/10 hover:border-lead-500 disabled:opacity-40 transition-colors"
                  >
                    <p className="text-xs text-fg truncate">
                      {save.name}
                      {loadedSave?.id === save.id && (
                        <span className="text-lead-500 ml-1.5">(loaded)</span>
                      )}
                    </p>
                    <p className="text-[10px] text-fg-muted">
                      {new Date(save.created_at).toLocaleString()}
                    </p>
                  </button>
                ))}
              </div>
              {overwriteMutation.isError && (
                <p className="text-[10px] text-stop">
                  {overwriteMutation.error.message}
                </p>
              )}
            </div>
          ) : (
            <form onSubmit={submitNewSave} className="space-y-2">
              <input
                type="text"
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Save name..."
                className="w-full bg-bay-800 border border-line rounded px-2 py-1.5 text-xs text-fg placeholder:text-fg-faint focus:outline-none focus:border-lead-500"
              />
              {createMutation.isError && (
                <p className="text-[10px] text-stop">
                  {createMutation.error.message}
                </p>
              )}
              <button
                type="submit"
                disabled={!name.trim() || createMutation.isPending}
                className="w-full flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium bg-lead-500/40 text-lead-500 border border-lead-500 hover:bg-lead-400/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {createMutation.isPending ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Save className="w-3.5 h-3.5" />
                )}
                Save
              </button>
            </form>
          )}
        </PopoverContent>
      </Popover>

      {restoreMutation.isError && (
        <span className="text-[10px] text-stop ml-1">
          {restoreMutation.error.message}
        </span>
      )}
    </div>
  );
}
