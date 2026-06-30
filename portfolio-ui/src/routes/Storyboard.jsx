import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import { useProjectStore } from '../stores/projectStore';
import { StorySummary } from '../components/storyboard/StorySummary';
import { SceneTable } from '../components/storyboard/SceneTable';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
import { Button } from '../components/ui/button';
import { Play, GitBranch, Loader2 } from 'lucide-react';

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

  if (isLoading) return <div className="flex justify-center p-12"><div className="animate-spin h-8 w-8 border-2 border-cyan-400 border-t-transparent rounded-full" /></div>;
  if (error) return <div className="text-center p-12 text-red-400">Failed to load project: {error.message}</div>;
  if (!project) return null;

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      {/* Project Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">{project.title || 'Untitled Project'}</h1>
          <p className="text-xs text-slate-500 mt-1">
            Created {new Date(project.created_at).toLocaleDateString()}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate(`/project/${id}/graph`)}
            className="border-white/10 text-slate-300 hover:text-white"
          >
            <GitBranch className="w-4 h-4 mr-1" />
            Graph
          </Button>
          <Button
            size="sm"
            onClick={handleRunAll}
            disabled={runningAll}
            className="bg-gradient-to-r from-blue-600 to-cyan-500 text-white disabled:opacity-60"
          >
            {runningAll ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Play className="w-4 h-4 mr-1" />}
            {runningAll ? 'Submitting...' : 'Run All Scenes'}
          </Button>
        </div>
      </div>

      {/* Story Summary */}
      <StorySummary summary={project.story_summary} />

      {/* Centered tab bar */}
      <Tabs defaultValue="storyboard" className="block">
        <TabsList variant="line" className="justify-center w-full border-b border-white/10 h-9 rounded-none bg-transparent">
          <TabsTrigger value="storyboard" className="text-xs px-3 py-1 text-slate-400 data-active:text-cyan-300">Storyboard</TabsTrigger>
          <TabsTrigger value="characters" className="text-xs px-3 py-1 text-slate-400 data-active:text-emerald-300">Characters</TabsTrigger>
          <TabsTrigger value="locations" className="text-xs px-3 py-1 text-slate-400 data-active:text-amber-300">Locations</TabsTrigger>
          <TabsTrigger value="props" className="text-xs px-3 py-1 text-slate-400 data-active:text-purple-300">Props</TabsTrigger>
        </TabsList>

        <div className="pt-6">
          <TabsContent value="storyboard">
            <SceneTable scenes={project.scenes || []} projectId={id} />
          </TabsContent>

          <TabsContent value="characters">
            <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6">
              <h3 className="text-lg font-semibold mb-4">Characters</h3>
              {project.characters && project.characters.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {project.characters.map((ch) => (
                    <div key={ch.id} className="bg-black/40 rounded-xl p-4 border border-white/5">
                      <h4 className="font-medium text-emerald-300">{ch.name}</h4>
                      {ch.description && <p className="text-xs text-slate-400 mt-1">{ch.description}</p>}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-slate-500 text-sm">No characters yet.</p>
              )}
            </div>
          </TabsContent>

          <TabsContent value="locations">
            <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6">
              <h3 className="text-lg font-semibold mb-4">Locations</h3>
              {project.locations && project.locations.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {project.locations.map((loc) => (
                    <div key={loc.id} className="bg-black/40 rounded-xl p-4 border border-white/5">
                      <h4 className="font-medium text-amber-300">{loc.name}</h4>
                      {loc.description && <p className="text-xs text-slate-400 mt-1">{loc.description}</p>}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-slate-500 text-sm">No locations yet.</p>
              )}
            </div>
          </TabsContent>

          <TabsContent value="props">
            <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6">
              <h3 className="text-lg font-semibold mb-4">Props</h3>
              {project.props && project.props.length > 0 ? (
                <div className="flex flex-wrap gap-3">
                  {project.props.map((p) => (
                    <div key={p.id} className="bg-black/40 rounded-xl px-4 py-2 border border-white/5">
                      <span className="text-sm text-purple-300">{p.name}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-slate-500 text-sm">No props yet.</p>
              )}
            </div>
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
