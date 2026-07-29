import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Box, Loader2 } from 'lucide-react';
import { api } from '../lib/api';
import { ScreenplayBlock } from '../components/scene/ScreenplayBlock';
import { SceneAssetSection } from '../components/scene/SceneAssetSection';
import { ShotList } from '../components/scene/ShotList';

export function SceneDetail() {
  const { id: projectId, sceneId } = useParams();

  const { data: scene, isLoading, error } = useQuery({
    queryKey: ['scene', sceneId],
    queryFn: () => api.getScene(sceneId),
  });

  if (isLoading) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none text-cyan-400" />
      </div>
    );
  }
  if (error) {
    return <div className="text-center p-12 text-red-400">Failed to load scene: {error.message}</div>;
  }
  if (!scene) return null;

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <Link
            to={`/project/${projectId}`}
            className="p-1.5 rounded text-slate-400 hover:text-white hover:bg-white/10 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40"
            title="Back to storyboard"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div className="min-w-0">
            <p className="text-xs font-bold text-cyan-400">SCENE {scene.scene_number}</p>
            <h1 className="text-xl font-bold text-white truncate">
              {scene.slugline || 'Untitled scene'}
            </h1>
          </div>
        </div>
        <Link
          to={`/project/${projectId}/scene/${sceneId}/stage`}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600/20 text-blue-300 hover:bg-blue-600/30 text-sm font-medium transition-colors shrink-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-blue-400"
        >
          <Box className="w-4 h-4" /> 3D Stage
        </Link>
      </div>

      <ScreenplayBlock scene={scene} />

      {/* Order per the brief: characters → props → locations */}
      <SceneAssetSection scene={scene} projectId={projectId} entityType="characters" />
      <SceneAssetSection scene={scene} projectId={projectId} entityType="props" />
      <SceneAssetSection scene={scene} projectId={projectId} entityType="locations" />

      <ShotList scene={scene} />
    </div>
  );
}
