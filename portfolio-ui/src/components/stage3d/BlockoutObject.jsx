import { useRef, useState, useEffect } from 'react';
import { TransformControls } from '@react-three/drei';
import { useStagingStore } from '@/stores/stagingStore';

const PRIMITIVE_GEOMETRY = {
  floor: { args: [4, 0.1, 4], color: '#4a5568' },
  box: { args: [1, 1, 1], color: '#718096' },
  plane: { args: [2, 0.02, 2], color: '#a0aec0' },
};

export function BlockoutObject({ blockout, selected, onSelect }) {
  const [meshObj, setMeshObj] = useState(null);
  const setBlockout = useStagingStore((s) => s.setBlockout);
  const blockoutList = useStagingStore((s) => s.blockout);
  const transformMode = useStagingStore((s) => s.transformMode);
  const transformRef = useRef();

  const prim = PRIMITIVE_GEOMETRY[blockout.kind] || PRIMITIVE_GEOMETRY.box;
  const pos = blockout.transform?.pos || [0, 0, 0];
  const rot = blockout.transform?.rot || [0, 0, 0];
  const scale = blockout.transform?.scale || [1, 1, 1];

  useEffect(() => {
    if (transformRef.current) {
      transformRef.current.setMode(transformMode);
    }
  }, [selected, transformMode]);

  const handleMouseUp = () => {
    if (!meshObj) return;
    const pos = meshObj.position.toArray();
    const { x, y, z } = meshObj.rotation;
    const scale = meshObj.scale.toArray();
    const updated = blockoutList.map((b) =>
      b.id === blockout.id
        ? { ...b, transform: { pos, rot: [x, y, z], scale } }
        : b
    );
    setBlockout(updated);
  };

  return (
    <group>
      <mesh
        ref={setMeshObj}
        position={pos}
        rotation={rot}
        scale={scale}
        onClick={(e) => {
          e.stopPropagation();
          onSelect();
        }}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <boxGeometry args={prim.args} />
        <meshStandardMaterial
          color={prim.color}
          transparent
          opacity={0.5}
          wireframe={blockout.kind === 'floor'}
        />
      </mesh>
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
