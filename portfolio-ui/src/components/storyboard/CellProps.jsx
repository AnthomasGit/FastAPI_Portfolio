import { SceneAssetCell } from './SceneAssetCell';

export function CellProps({ scene, projectId }) {
  return <SceneAssetCell scene={scene} projectId={projectId} entityType="props" />;
}
