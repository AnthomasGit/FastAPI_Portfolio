import { useEffect, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useStagingStore } from '@/stores/stagingStore';
import { ArrowLeft, Loader2 } from 'lucide-react';
import { StageCanvas } from '@/components/stage3d/StageCanvas';
import { StageToolbar } from '@/components/stage3d/StageToolbar';
import { PipelinePanel } from '@/components/stage3d/PipelinePanel';
import { AssetDrawer } from '@/components/stage3d/AssetDrawer';
import { StagingSaves } from '@/components/stage3d/StagingSaves';
import { BackdropPicker } from '@/components/stage3d/BackdropPicker';
import { ShotControls } from '@/components/stage3d/ShotControls';
import { useLocationReferences } from '@/components/stage3d/useLocationReferences';

export function SceneStage() {
  const { id: projectId, sceneId } = useParams();
  const queryClient = useQueryClient();
  const hydrateFromServer = useStagingStore((s) => s.hydrateFromServer);
  const getUpdatePayload = useStagingStore((s) => s.getUpdatePayload);
  const dirty = useStagingStore((s) => s.dirty);
  const editVersion = useStagingStore((s) => s.editVersion);
  const setDirty = useStagingStore((s) => s.setDirty);
  const autosaveTimer = useRef(null);
  const hydratedSceneRef = useRef(null);

  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.getProject(projectId),
  });

  const scene = project?.scenes?.find((s) => s.id === sceneId);

  const { data: staging, isLoading: stagingLoading } = useQuery({
    queryKey: ['staging', sceneId],
    queryFn: () => api.getStaging(sceneId),
    enabled: !!sceneId,
  });

  useEffect(() => {
    if (staging && hydratedSceneRef.current !== sceneId) {
      hydrateFromServer(staging);
      hydratedSceneRef.current = sceneId;
    }
  }, [staging, sceneId, hydrateFromServer]);

  const saveMutation = useMutation({
    mutationFn: ({ payload }) => api.putStaging(sceneId, payload),
    onSuccess: (data, { version }) => {
      queryClient.setQueryData(['staging', sceneId], data);
      if (useStagingStore.getState().editVersion === version) {
        setDirty(false);
      }
    },
  });

  const { mutate: saveStaging, isPending: savePending } = saveMutation;

  useEffect(() => {
    if (!dirty || savePending) return;
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => {
      saveStaging({
        payload: getUpdatePayload(),
        version: useStagingStore.getState().editVersion,
      });
    }, 2000);
    return () => {
      if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    };
  }, [dirty, editVersion, savePending, getUpdatePayload, saveStaging]);

  // Undo/redo shortcuts, bound at the DOM route level (not inside the R3F
  // Canvas) so the window listener attaches reliably: Ctrl/Cmd+Z undo,
  // Ctrl/Cmd+Shift+Z or Ctrl+Y redo. Ignored while typing in a field.
  useEffect(() => {
    const handler = (e) => {
      const t = e.target;
      if (
        t instanceof HTMLElement &&
        (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
      ) return;
      if (!(e.ctrlKey || e.metaKey)) return;
      const key = e.key.toLowerCase();
      const store = useStagingStore.getState();
      if (key === 'z') {
        e.preventDefault();
        if (e.shiftKey) store.redo();
        else store.undo();
      } else if (key === 'y') {
        e.preventDefault();
        store.redo();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const { data: captures, isLoading: capturesLoading } = useQuery({
    queryKey: ['captures', sceneId],
    queryFn: () => api.listCaptures(sceneId),
    enabled: !!sceneId,
  });

  const projectCharacters = project?.characters || [];
  const projectProps = project?.props || [];
  const sceneCharacters = scene?.characters || [];
  const sceneLocations = scene?.locations || [];
  const sceneProps = scene?.props || [];

  const backdropReferenceId = useStagingStore((s) => s.backdropReferenceId);
  const { references: locationReferences } = useLocationReferences(sceneLocations);
  const backdropRef = locationReferences.find((r) => r.id === backdropReferenceId);
  const backdropUrl = backdropRef ? api.getReferenceFileUrl(backdropRef) : null;

  if (!scene) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400">
        {stagingLoading ? (
          <Loader2 className="w-6 h-6 animate-spin" />
        ) : (
          'Scene not found'
        )}
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-slate-950">
      <header className="border-b border-white/10 backdrop-blur-md bg-black/30 px-4 h-12 flex items-center shrink-0 z-50">
        <div className="flex-1 flex items-center gap-3 min-w-0">
          <Link
            to={`/project/${projectId}`}
            className="text-slate-400 hover:text-white transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <span className="text-sm font-medium text-white truncate max-w-[200px]">
            {scene.slugline || `Scene ${scene.scene_number}`}
          </span>
          <span className="text-xs text-slate-500">3D Stage</span>
          {dirty && (
            <span className="text-xs text-amber-400 animate-pulse">Unsaved changes...</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {/* key: reset loaded-save/popover state when switching scenes */}
          <StagingSaves key={sceneId} sceneId={sceneId} />
          <div className="w-px h-5 bg-white/10" />
          <BackdropPicker sceneLocations={sceneLocations} />
          <div className="w-px h-5 bg-white/10" />
          <ShotControls />
        </div>
        <div className="flex-1 flex justify-end">
          <StageToolbar />
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="border-b border-white/10 bg-white/[0.02] px-4 py-2.5 space-y-1 shrink-0">
            <div className="flex items-center gap-3">
              <span className="text-xs font-bold text-cyan-400">SC {scene.scene_number}</span>
              <span className="text-sm text-slate-200">{scene.slugline}</span>
            </div>
            {scene.screenplay && (
              <p className="text-[11px] text-slate-400 line-clamp-2 leading-relaxed">
                {scene.screenplay}
              </p>
            )}
            <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[10px] text-slate-500">
              {sceneCharacters.length > 0 && (
                <span>
                  <span className="text-emerald-400 font-medium">Characters</span>
                  {' '}{sceneCharacters.map((c) => c.name).join(', ')}
                </span>
              )}
              {sceneLocations.length > 0 && (
                <span>
                  <span className="text-amber-400 font-medium">Locations</span>
                  {' '}{sceneLocations.map((l) => l.name).join(', ')}
                </span>
              )}
              {sceneProps.length > 0 && (
                <span>
                  <span className="text-purple-400 font-medium">Props</span>
                  {' '}{sceneProps.map((p) => p.name).join(', ')}
                </span>
              )}
            </div>
          </div>
          <div className="flex-1 relative">
          <StageCanvas
            sceneId={sceneId}
            backdropUrl={backdropUrl}
          />
          </div>
        </div>

        <aside className="w-80 border-l border-white/10 bg-black/20 overflow-y-auto shrink-0">
          <div className="p-4 space-y-6">
            <div>
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Captures
              </h3>
              <PipelinePanel
                captures={captures || []}
                isLoading={capturesLoading}
                sceneId={sceneId}
                sceneNumber={scene.scene_number}
              />
            </div>

            <div>
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Assets
              </h3>
              <AssetDrawer
                projectId={projectId}
                characters={projectCharacters}
                props={projectProps}
              />
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
