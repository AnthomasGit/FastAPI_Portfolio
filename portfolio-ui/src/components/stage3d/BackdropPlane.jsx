import { Suspense, useEffect, useRef, useState } from 'react';
import { useTexture, TransformControls } from '@react-three/drei';
import { useStagingStore } from '@/stores/stagingStore';
import { StageErrorBoundary } from './StageErrorBoundary';

const DEFAULT_POS = [0, 1.5, -5];
const DEFAULT_ROT = [0, 0, 0];
const DEFAULT_SCALE = [4, 3, 1];

function PlaceholderMesh({ meshRef, pos, rot, scale, onSelect, color }) {
  return (
    <mesh
      ref={meshRef}
      position={pos}
      rotation={rot}
      scale={scale}
      userData={{ isBackdrop: true }}
      onClick={(e) => { e.stopPropagation(); onSelect(); }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <planeGeometry args={[4, 3]} />
      <meshStandardMaterial color={color} side={1} />
    </mesh>
  );
}

function BackdropImage({ url, meshRef, pos, rot, scale, onSelect }) {
  const texture = useTexture(url);
  return (
    <mesh
      ref={meshRef}
      position={pos}
      rotation={rot}
      scale={scale}
      userData={{ isBackdrop: true }}
      onClick={(e) => { e.stopPropagation(); onSelect(); }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <planeGeometry args={[4, 3]} />
      <meshBasicMaterial map={texture} side={1} toneMapped={false} />
    </mesh>
  );
}

export function BackdropPlane({ url, selected, onSelect }) {
  const [meshObj, setMeshObj] = useState(null);
  const transformRef = useRef();
  const backdropTransform = useStagingStore((s) => s.backdropTransform);
  const setBackdropTransform = useStagingStore((s) => s.setBackdropTransform);
  const transformMode = useStagingStore((s) => s.transformMode);

  const pos = backdropTransform?.pos || DEFAULT_POS;
  const rot = backdropTransform?.rot || DEFAULT_ROT;
  const scale = backdropTransform?.scale || DEFAULT_SCALE;

  useEffect(() => {
    if (transformRef.current) {
      transformRef.current.setMode(transformMode);
    }
  }, [selected, transformMode]);

  const handleMouseUp = () => {
    if (!meshObj) return;
    setBackdropTransform({
      pos: meshObj.position.toArray(),
      rot: [meshObj.rotation.x, meshObj.rotation.y, meshObj.rotation.z],
      scale: meshObj.scale.toArray(),
    });
  };

  const meshProps = { meshRef: setMeshObj, pos, rot, scale, onSelect };

  return (
    <group>
      {url ? (
        <Suspense fallback={<PlaceholderMesh {...meshProps} color="#334155" />}>
          <StageErrorBoundary fallback={<PlaceholderMesh {...meshProps} color="#ef4444" />}>
            <BackdropImage url={url} {...meshProps} />
          </StageErrorBoundary>
        </Suspense>
      ) : (
        <PlaceholderMesh {...meshProps} color="#1e293b" />
      )}
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
