import { SceneAssetCell } from './SceneAssetCell';

export function CellCharacters({ scene, projectId }) {
  return <SceneAssetCell scene={scene} projectId={projectId} entityType="characters" />;
}
