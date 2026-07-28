import { Suspense, useRef, useState, useEffect, useCallback, useMemo } from 'react';
import { useGLTF, TransformControls } from '@react-three/drei';
import { useStagingStore } from '@/stores/stagingStore';
import { StageErrorBoundary } from './StageErrorBoundary';

function disposeMaterial(mat) {
  if (!mat) return;
  const textures = [
    mat.map, mat.lightMap, mat.aoMap, mat.emissiveMap,
    mat.bumpMap, mat.normalMap, mat.displacementMap,
    mat.roughnessMap, mat.metalnessMap, mat.alphaMap,
    mat.envMap, mat.specularMap,
  ];
  textures.forEach((t) => t?.dispose());
  mat.dispose();
}

function disposeScene(obj) {
  obj.traverse((child) => {
    if (child.isMesh) {
      child.geometry?.dispose();
      if (Array.isArray(child.material)) {
        child.material.forEach(disposeMaterial);
      } else {
        disposeMaterial(child.material);
      }
    }
  });
}

function MeshAsset({ url, pos, rot, scl, onSelect, onMeshRef }) {
  const { scene } = useGLTF(url);
  const cloned = useMemo(() => scene.clone(), [scene]);

  useEffect(() => {
    return () => disposeScene(cloned);
  }, [cloned]);

  return (
    <primitive
      ref={onMeshRef}
      object={cloned}
      position={pos}
      rotation={rot}
      scale={scl}
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
      }}
      onPointerDown={(e) => e.stopPropagation()}
      castShadow
      receiveShadow
    />
  );
}

export function PlacedAsset({ placement, selected, onSelect, onUpdate }) {
  const [meshObj, setMeshObj] = useState(null);
  const transformRef = useRef();
  const transformMode = useStagingStore((s) => s.transformMode);
  const gltfUrl = `/api/assets3d/${placement.asset3d_id}/mesh`;
  const pos = placement.transform?.pos || [0, 0, 0];
  const rot = placement.transform?.rot || [0, 0, 0];
  const scl = placement.transform?.scale || [1, 1, 1];

  useEffect(() => {
    return () => setMeshObj(null);
  }, [setMeshObj]);

  useEffect(() => {
    if (transformRef.current) {
      transformRef.current.setMode(transformMode);
    }
  }, [selected, transformMode]);

  const handleMouseUp = useCallback(() => {
    if (!meshObj) return;
    onUpdate({
      transform: {
        pos: meshObj.position.toArray(),
        rot: [meshObj.rotation.x, meshObj.rotation.y, meshObj.rotation.z],
        scale: meshObj.scale.toArray(),
      },
    });
  }, [meshObj, onUpdate]);

  return (
    <group userData={{ isStagingObject: true }}>
      <Suspense
        fallback={
          <mesh
            position={pos}
            scale={scl}
            onClick={(e) => { e.stopPropagation(); onSelect(); }}
            onPointerDown={(e) => e.stopPropagation()}
          >
            <boxGeometry args={[0.5, 0.5, 0.5]} />
            <meshStandardMaterial color="#f59e0b" wireframe />
          </mesh>
        }
      >
        <StageErrorBoundary
          fallback={
            <mesh
              position={pos}
              scale={scl}
              onClick={(e) => { e.stopPropagation(); onSelect(); }}
              onPointerDown={(e) => e.stopPropagation()}
            >
              <boxGeometry args={[0.5, 0.5, 0.5]} />
              <meshStandardMaterial color="#ef4444" wireframe />
            </mesh>
          }
        >
          <MeshAsset
            url={gltfUrl}
            pos={pos}
            rot={rot}
            scl={scl}
            onSelect={onSelect}
            onMeshRef={setMeshObj}
          />
        </StageErrorBoundary>
      </Suspense>
      {selected && meshObj && (
        <TransformControls
          ref={transformRef}
          object={meshObj}
          mode={transformMode}
          onMouseUp={handleMouseUp}
        />
      )}
    </group>
  );
}
