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
      <div className="flex justify-center p-16">
        <Loader2 className="w-5 h-5 animate-spin text-lead-500" />
      </div>
    );
  }
  if (error) {
    return (
      <p role="alert" className="max-w-2xl mx-auto mt-10 rounded-frame border border-stop/30 bg-stop/15 px-3 py-2 text-xs text-stop">
        Couldn't load this scene: {error.message}
      </p>
    );
  }
  if (!scene) return null;

  return (
    <div className="max-w-5xl mx-auto px-5 py-8 space-y-7">
      {/* The slate, at page scale — the same device that marks a row in the
          storyboard table, so a scene reads the same wherever you meet it. */}
      <header>
        <div className="clapper h-1 w-full mb-4" aria-hidden="true" />
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0">
            <Link
              to={`/project/${projectId}`}
              className="mt-1 rounded-frame p-1.5 text-fg-muted hover:text-fg hover:bg-bay-800 transition-colors"
              title="Back to storyboard"
            >
              <ArrowLeft className="w-4 h-4" />
            </Link>
            <div className="min-w-0">
              <p className="label-slug mb-1.5">Scene {scene.scene_number}</p>
              <h1 className="font-mono text-xl font-bold uppercase tracking-wide text-fg">
                {scene.slugline || <span className="normal-case tracking-normal font-normal text-fg-faint">Untitled scene</span>}
              </h1>
            </div>
          </div>
          <Link
            to={`/project/${projectId}/scene/${sceneId}/stage`}
            className="flex items-center gap-1.5 shrink-0 rounded-frame border border-line px-3 py-2 text-xs text-fg-muted hover:text-fg hover:bg-bay-800 transition-colors"
          >
            <Box className="w-3.5 h-3.5" /> Block it in 3D
          </Link>
        </div>
      </header>

      <ScreenplayBlock scene={scene} />

      {/* Order per the brief: characters → props → locations */}
      <SceneAssetSection scene={scene} projectId={projectId} entityType="characters" />
      <SceneAssetSection scene={scene} projectId={projectId} entityType="props" />
      <SceneAssetSection scene={scene} projectId={projectId} entityType="locations" />

      <ShotList scene={scene} />
    </div>
  );
}
