import { Suspense, useEffect } from 'react';
import { Canvas } from '@react-three/fiber';
import { Environment, Grid } from '@react-three/drei';
import { BackdropPlane } from './BackdropPlane';
import { BlockoutObject } from './BlockoutObject';
import { PlacedAsset } from './PlacedAsset';
import { CameraRig } from './CameraRig';
import { CaptureRenderer } from './CaptureRenderer';
import { ShotPreview } from './ShotPreview';
import { getFormat, pipSize, PIP_MARGIN } from './cameraFormats';
import { useStagingStore } from '@/stores/stagingStore';

function SceneContent({ captures, backdropUrl }) {
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
      const t = e.target;
      if (
        t instanceof HTMLElement &&
        (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
      ) return;
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

      <BackdropPlane
        url={backdropUrl}
        selected={selection === 'backdrop'}
        onSelect={() => setSelection('backdrop')}
      />

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
      <ShotPreview />
      <CaptureRenderer captures={captures} />
    </>
  );
}

// HTML overlay: a border + label around the WebGL corner preview, positioned to
// match the scissor rect in ShotPreview (bottom-right, PIP_MARGIN inset).
function ShotPreviewFrame() {
  const camera = useStagingStore((s) => s.camera);
  if (!camera) return null;
  const fmt = getFormat(camera.format);
  const { pw, ph } = pipSize(fmt.aspect);
  return (
    <div
      className="absolute pointer-events-none rounded-sm ring-1 ring-cyan-400/60"
      style={{ right: PIP_MARGIN, bottom: PIP_MARGIN, width: pw, height: ph }}
    >
      <div className="absolute -top-5 left-0 text-[10px] font-medium text-cyan-300 tabular-nums">
        {camera.focal_length}mm · {fmt.id}
      </div>
    </div>
  );
}

export function StageCanvas({ captures, backdropUrl }) {
  return (
    <div className="w-full h-full relative">
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
        <SceneContent captures={captures} backdropUrl={backdropUrl} />
        <Suspense fallback={null}>
          <Environment preset="studio" />
        </Suspense>
      </Canvas>
      <ShotPreviewFrame />
    </div>
  );
}
