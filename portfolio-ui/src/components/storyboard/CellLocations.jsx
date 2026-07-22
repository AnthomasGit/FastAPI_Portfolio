import { SceneAssetCell } from './SceneAssetCell';

export function CellLocations({ scene, projectId }) {
  return <SceneAssetCell scene={scene} projectId={projectId} entityType="locations" />;
}
