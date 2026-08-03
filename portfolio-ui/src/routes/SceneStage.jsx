import { useEffect, useRef, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useStagingStore } from '@/stores/stagingStore';
import { ArrowLeft, ChevronRight, PanelRightClose, PanelRightOpen, Loader2 } from 'lucide-react';
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
  const [sidebarOpen, setSidebarOpen] = useState(true);

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
      <div className="flex items-center justify-center h-64 text-fg-muted">
        {stagingLoading ? (
          <Loader2 className="w-6 h-6 animate-spin" />
        ) : (
          'Scene not found'
        )}
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-bay-850">
      <header className="border-b border-line bg-bay-900 px-4 h-12 flex items-center shrink-0 z-50">
        <div className="flex-1 flex items-center gap-3 min-w-0">
          <Link
            to={`/project/${projectId}`}
            className="text-fg-muted hover:text-fg transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <span className="text-sm font-medium text-fg truncate max-w-[200px]">
            {scene.slugline || `Scene ${scene.scene_number}`}
          </span>
          <span className="text-xs text-fg-muted">3D Stage</span>
          {dirty && (
            <span className="text-xs text-set animate-pulse">Unsaved changes...</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {/* key: reset loaded-save/popover state when switching scenes */}
          <StagingSaves key={sceneId} sceneId={sceneId} />
          <div className="w-px h-5 bg-bay-700" />
          <BackdropPicker sceneLocations={sceneLocations} />
          <div className="w-px h-5 bg-bay-700" />
          <ShotControls />
        </div>
        <div className="flex-1 flex justify-end">
          <StageToolbar />
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="border-b border-line bg-bay-800 px-4 py-2.5 space-y-1 shrink-0">
            <div className="flex items-center gap-3">
              <span className="text-xs font-bold text-lead-500">SC {scene.scene_number}</span>
              <span className="text-sm text-fg">{scene.slugline}</span>
            </div>
            {scene.screenplay && (
              <p className="text-[11px] text-fg-muted line-clamp-2 leading-relaxed">
                {scene.screenplay}
              </p>
            )}
            <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[10px] text-fg-muted">
              {sceneCharacters.length > 0 && (
                <span>
                  <span className="text-cast font-medium">Characters</span>
                  {' '}{sceneCharacters.map((c) => c.name).join(', ')}
                </span>
              )}
              {sceneLocations.length > 0 && (
                <span>
                  <span className="text-set font-medium">Locations</span>
                  {' '}{sceneLocations.map((l) => l.name).join(', ')}
                </span>
              )}
              {sceneProps.length > 0 && (
                <span>
                  <span className="text-prop font-medium">Props</span>
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

        <div className="relative shrink-0 flex">
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            className="w-6 border-l border-line bg-bay-900 hover:bg-bay-800 flex items-start justify-center pt-3 text-fg-muted hover:text-fg transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-lead-500 shrink-0"
          >
            {sidebarOpen ? <PanelRightClose className="w-3.5 h-3.5" /> : <PanelRightOpen className="w-3.5 h-3.5" />}
          </button>

          {sidebarOpen && (
            <aside className="w-80 border-l border-line bg-bay-900 overflow-y-auto shrink-0">
              <div className="p-4 space-y-6">
                <details className="group" open>
                  <summary className="flex items-center gap-1.5 text-xs font-semibold text-fg-muted uppercase tracking-wider mb-3 cursor-pointer select-none hover:text-fg transition-colors list-none [&::-webkit-details-marker]:hidden [&::marker]:hidden">
                    <ChevronRight className="w-3 h-3 shrink-0 transition-transform group-open:rotate-90" />
                    Captures
                  </summary>
                  <PipelinePanel
                    captures={captures || []}
                    isLoading={capturesLoading}
                    sceneId={sceneId}
                    sceneNumber={scene.scene_number}
                  />
                </details>

                <details className="group" open>
                  <summary className="flex items-center gap-1.5 text-xs font-semibold text-fg-muted uppercase tracking-wider mb-3 cursor-pointer select-none hover:text-fg transition-colors list-none [&::-webkit-details-marker]:hidden [&::marker]:hidden">
                    <ChevronRight className="w-3 h-3 shrink-0 transition-transform group-open:rotate-90" />
                    Assets
                  </summary>
                  <AssetDrawer
                    projectId={projectId}
                    characters={projectCharacters}
                    props={projectProps}
                  />
                </details>
              </div>
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
