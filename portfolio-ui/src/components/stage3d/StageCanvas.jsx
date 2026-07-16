import { Suspense, useEffect } from 'react';
import { Canvas } from '@react-three/fiber';
import { Environment, Grid } from '@react-three/drei';
import { BackdropPlane } from './BackdropPlane';
import { BlockoutObject } from './BlockoutObject';
import { PlacedAsset } from './PlacedAsset';
import { CameraRig } from './CameraRig';
import { CaptureRenderer } from './CaptureRenderer';
import { useStagingStore } from '@/stores/stagingStore';

function SceneContent({ projectId, captures }) {
  const placements = useStagingStore((s) => s.placements);
  const blockout = useStagingStore((s) => s.blockout);
  const selection = useStagingStore((s) => s.selection);
  const setSelection = useStagingStore((s) => s.setSelection);
  const setPlacements = useStagingStore((s) => s.setPlacements);
  const removeBlockout = useStagingStore((s) => s.removeBlockout);
  const removePlacement = useStagingStore((s) => s.removePlacement);

  useEffect(() => {
    const handler = (e) => {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return;
      const sel = selection;
      if (!sel) return;
      if (blockout.some((b) => b.id === sel)) removeBlockout(sel);
      if (placements.some((p) => p.id === sel)) removePlacement(sel);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [selection, blockout, placements, removeBlockout, removePlacement]);

  return (
    <>
      <ambientLight intensity={0.5} />
      <directionalLight position={[10, 10, 5]} intensity={1} castShadow />
      <directionalLight position={[-5, 5, -5]} intensity={0.3} />
      <Grid
        position={[0, -0.01, 0]}
        args={[20, 20]}
        cellSize={1}
        cellThickness={0.5}
        cellColor="#6b7280"
        sectionSize={5}
        sectionThickness={1}
        sectionColor="#9ca3af"
        fadeDistance={30}
        infiniteGrid
      />

      <BackdropPlane />

      {blockout.map((obj) => (
        <BlockoutObject
          key={obj.id}
          blockout={obj}
          selected={selection === obj.id}
          onSelect={() => setSelection(obj.id)}
        />
      ))}

      {placements.map((p) => (
        <PlacedAsset
          key={p.id}
          placement={p}
          selected={selection === p.id}
          onSelect={() => setSelection(p.id)}
          onUpdate={(updates) => {
            setPlacements(
              placements.map((pl) => (pl.id === p.id ? { ...pl, ...updates } : pl))
            );
          }}
        />
      ))}

      <CameraRig />
      <CaptureRenderer captures={captures} />
    </>
  );
}

export function StageCanvas({ sceneId, projectId, captures }) {
  return (
    <Canvas
      shadows
      dpr={[1, 1.5]}
      camera={{ position: [5, 5, 5], fov: 45 }}
      gl={{
        preserveDrawingBuffer: true,
        powerPreference: 'high-performance',
      }}
      onCreated={({ gl }) => {
        gl.domElement.addEventListener('webglcontextlost', (e) => {
          e.preventDefault();
          console.warn('WebGL context lost');
        });
      }}
      className="w-full h-full"
    >
      <color attach="background" args={['#1e293b']} />
      <SceneContent projectId={projectId} captures={captures} />
      <Suspense fallback={null}>
        <Environment preset="studio" />
      </Suspense>
    </Canvas>
  );
}
