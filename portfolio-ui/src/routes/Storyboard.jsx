import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import { useProjectStore } from '../stores/projectStore';
import { StorySummary } from '../components/storyboard/StorySummary';
import { SceneTable } from '../components/storyboard/SceneTable';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
import { Play, GitBranch, Loader2 } from 'lucide-react';
import { AssetDrawer } from '@/components/stage3d/AssetDrawer';
import { EntityAssetLibrary } from '../components/storyboard/EntityAssetLibrary';
import { LocationPlatePanel } from '../components/storyboard/LocationPlatePanel';
import { PooledAssetGallery } from '../components/storyboard/PooledAssetGallery';
import { QueuePanel } from '../components/queue/QueuePanel';

function DeptPanel({ title, count, accent, empty, children }) {
  return (
    <section className="rounded-frame border border-line bg-bay-850">
      <header className="flex items-center gap-2 px-4 py-3 border-b border-line">
        <h2 className={`text-sm font-semibold ${accent}`}>{title}</h2>
        <span className="font-mono text-[11px] text-fg-faint">{count}</span>
      </header>
      <div className="p-4">
        {count === 0 ? <p className="text-xs text-fg-faint">{empty}</p> : children}
      </div>
    </section>
  );
}

export function Storyboard() {
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const setCurrentProject = useProjectStore((s) => s.setCurrentProject);
  const [runningAll, setRunningAll] = useState(false);

  const { data: project, isLoading, error } = useQuery({
    queryKey: ['project', id],
    queryFn: () => api.getProject(id),
  });

  const handleRunAll = async () => {
    setRunningAll(true);
    try {
      await api.generateProject(id);
      queryClient.invalidateQueries({ queryKey: ['project', id] });
    } catch (e) {
      console.error('Run All failed', e);
    }
    setRunningAll(false);
  };

  useEffect(() => {
    if (project) setCurrentProject(project);
    return () => setCurrentProject(null);
  }, [project, setCurrentProject]);

  if (isLoading) {
    return (
      <div className="flex justify-center p-16">
        <Loader2 className="w-5 h-5 animate-spin text-lead-500" />
      </div>
    );
  }
  if (error) {
    return (
      <p role="alert" className="max-w-2xl mx-auto mt-10 rounded-frame border border-stop/40 bg-stop/10 px-3 py-2 text-xs text-stop">
        Couldn't load this project: {error.message}
      </p>
    );
  }
  if (!project) return null;

  const scenes = project.scenes || [];
  const characters = project.characters || [];
  const locations = project.locations || [];
  const props = project.props || [];

  const tab = 'text-[11px] px-3 py-1.5 font-medium text-fg-muted hover:text-fg transition-colors';

  return (
    <div className="max-w-[1600px] mx-auto px-5 py-8">
      <div className="flex items-end justify-between gap-4 mb-5 pb-4 border-b border-line">
        <div className="min-w-0">
          <p className="label-slug mb-1.5">
            Production · {scenes.length} scene{scenes.length === 1 ? '' : 's'}
          </p>
          <h1 className="font-mono text-2xl font-bold text-fg truncate">
            {project.title || 'Untitled project'}
          </h1>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => navigate(`/project/${id}/graph`)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-frame border border-line text-xs text-fg-muted hover:text-fg hover:bg-bay-800 transition-colors"
          >
            <GitBranch className="w-3.5 h-3.5" /> Graph
          </button>
          <button
            onClick={handleRunAll}
            disabled={runningAll}
            className="flex items-center gap-1.5 px-3 py-2 rounded-frame bg-lead-500 text-bay-950 text-xs font-semibold hover:bg-lead-400 transition-colors disabled:bg-bay-700 disabled:text-fg-faint"
            title="Queue an image for every scene in this project"
          >
            {runningAll ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            {runningAll ? 'Queueing…' : 'Render all scenes'}
          </button>
        </div>
      </div>

      <StorySummary summary={project.story_summary} />

      <Tabs defaultValue="storyboard" className="block">
        <TabsList variant="line" className="w-full justify-start gap-1 border-b border-line h-9 rounded-none bg-transparent p-0">
          <TabsTrigger value="storyboard" className={`${tab} data-active:text-fg`}>Storyboard</TabsTrigger>
          <TabsTrigger value="characters" className={`${tab} data-active:text-cast`}>Characters</TabsTrigger>
          <TabsTrigger value="locations" className={`${tab} data-active:text-set`}>Locations</TabsTrigger>
          <TabsTrigger value="props" className={`${tab} data-active:text-prop`}>Props</TabsTrigger>
          <TabsTrigger value="assets3d" className={`${tab} data-active:text-fg`}>3D assets</TabsTrigger>
          <TabsTrigger value="queue" className={`${tab} data-active:text-fg`}>Queue</TabsTrigger>
        </TabsList>

        <div className="pt-5">
          <TabsContent value="storyboard">
            <SceneTable scenes={scenes} projectId={id} />
          </TabsContent>

          <TabsContent value="characters">
            <PooledAssetGallery entityType="characters" projectId={id} />
            <DeptPanel title="Characters" count={characters.length} accent="text-cast" empty="No characters yet. Add them from a scene.">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
                {characters.map((ch) => (
                  <div key={ch.id} className="rounded-frame border border-line bg-bay-900 p-3">
                    <h3 className="font-mono text-sm font-bold text-cast">{ch.name}</h3>
                    {ch.description && <p className="text-xs text-fg-muted mt-1.5 leading-relaxed">{ch.description}</p>}
                    <EntityAssetLibrary entityType="character" entityId={ch.id} entityName={ch.name} projectId={id} canonicalAssetImageId={ch.canonical_asset_image_id} />
                  </div>
                ))}
              </div>
            </DeptPanel>
          </TabsContent>

          <TabsContent value="locations">
            <PooledAssetGallery entityType="locations" projectId={id} />
            <DeptPanel title="Locations" count={locations.length} accent="text-set" empty="No locations yet. Add them from a scene.">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
                {locations.map((loc) => (
                  <div key={loc.id} className="rounded-frame border border-line bg-bay-900 p-3">
                    <h3 className="font-mono text-sm font-bold text-set">{loc.name}</h3>
                    {loc.description && <p className="text-xs text-fg-muted mt-1.5 leading-relaxed">{loc.description}</p>}
                    <LocationPlatePanel location={loc} projectId={id} />
                    <EntityAssetLibrary entityType="location" entityId={loc.id} entityName={loc.name} projectId={id} />
                  </div>
                ))}
              </div>
            </DeptPanel>
          </TabsContent>

          <TabsContent value="props">
            <PooledAssetGallery entityType="props" projectId={id} />
            <DeptPanel title="Props" count={props.length} accent="text-prop" empty="No props yet. Add them from a scene.">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
                {props.map((p) => (
                  <div key={p.id} className="rounded-frame border border-line bg-bay-900 p-3">
                    <h3 className="font-mono text-sm font-bold text-prop">{p.name}</h3>
                    {p.description && <p className="text-xs text-fg-muted mt-1.5 leading-relaxed">{p.description}</p>}
                    <EntityAssetLibrary entityType="prop" entityId={p.id} entityName={p.name} projectId={id} />
                  </div>
                ))}
              </div>
            </DeptPanel>
          </TabsContent>

          <TabsContent value="assets3d">
            <section className="rounded-frame border border-line bg-bay-850">
              <header className="flex items-center gap-2 px-4 py-3 border-b border-line">
                <h2 className="text-sm font-semibold text-fg">3D assets</h2>
              </header>
              <div className="p-4">
                <AssetDrawer projectId={id} characters={characters} props={props} />
              </div>
            </section>
          </TabsContent>

          <TabsContent value="queue">
            <QueuePanel projectId={id} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
