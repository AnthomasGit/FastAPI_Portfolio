import { Suspense, useEffect, useRef, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { Maximize2 } from 'lucide-react';
import { Environment, Grid } from '@react-three/drei';
import { BackdropPlane } from './BackdropPlane';
import { BlockoutObject } from './BlockoutObject';
import { PlacedAsset } from './PlacedAsset';
import { CameraRig } from './CameraRig';
import { CaptureRenderer } from './CaptureRenderer';
import { ShotPreview } from './ShotPreview';
import { PilotControls } from './PilotControls';
import { AssetFlyControls } from './AssetFlyControls';
import { getFormat, pipSize, gateRect, PIP_MARGIN } from './cameraFormats';
import { useStagingStore } from '@/stores/stagingStore';

function SceneContent({ sceneId, backdropUrl }) {
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

  // Shift toggles fast mode for all keyboard movement (nav fly, pilot, asset
  // nudge). One listener for the whole editor so a single press flips it once.
  useEffect(() => {
    const handler = (e) => {
      if (e.key !== 'Shift' || e.repeat) return;
      const t = e.target;
      if (
        t instanceof HTMLElement &&
        (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
      ) return;
      useStagingStore.getState().toggleFastMode();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

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
      <PilotControls />
      <AssetFlyControls />
      <CaptureRenderer sceneId={sceneId} />
    </>
  );
}

// HTML overlay companion to ShotPreview's WebGL output. Normal mode: border +
// label around the corner PiP. Pilot mode: the through-the-lens gate frame with
// key legend, matching the centered scissor rect pixel-for-pixel.
function ShotPreviewFrame() {
  const camera = useStagingStore((s) => s.camera);
  const pilotMode = useStagingStore((s) => s.pilotMode);
  const pipScale = useStagingStore((s) => s.pipScale);
  const cyclePipScale = useStagingStore((s) => s.cyclePipScale);
  const wrapRef = useRef(null);
  const [box, setBox] = useState(null);

  // Track the canvas box while piloting so the DOM gate matches the WebGL one.
  // (ResizeObserver delivers an initial measurement on observe.)
  useEffect(() => {
    if (!pilotMode) return;
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() =>
      setBox({ w: el.clientWidth, h: el.clientHeight })
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, [pilotMode]);

  if (!camera) return null;
  const fmt = getFormat(camera.format);

  if (pilotMode) {
    const gate = box ? gateRect(fmt.aspect, box.w, box.h) : null;
    return (
      <div ref={wrapRef} className="absolute inset-0 pointer-events-none">
        {gate && (
          <div
            className="absolute ring-2 ring-cyan-400/70 rounded-sm"
            style={{ left: gate.x, top: gate.y, width: gate.gw, height: gate.gh }}
          >
            <div className="absolute top-2 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded bg-black/60 text-[10px] font-semibold text-cyan-300 tracking-wider whitespace-nowrap">
              PILOT · WASD/QE move · ←→ pan · ↑↓ tilt · Shift speed · Esc done
            </div>
            <div className="absolute bottom-2 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded bg-black/60 text-[10px] font-medium text-cyan-300 tabular-nums">
              {camera.focal_length}mm · {fmt.id}
            </div>
          </div>
        )}
      </div>
    );
  }

  const { pw, ph } = pipSize(fmt.aspect, pipScale);
  return (
    <div
      className="absolute pointer-events-none rounded-sm ring-1 ring-cyan-400/60"
      style={{ right: PIP_MARGIN, bottom: PIP_MARGIN, width: pw, height: ph }}
    >
      <div className="absolute -top-5 left-0 text-[10px] font-medium text-cyan-300 tabular-nums">
        {camera.focal_length}mm · {fmt.id}
      </div>
      <button
        type="button"
        onClick={cyclePipScale}
        title="Resize preview"
        className="pointer-events-auto absolute -top-5 right-0 flex items-center gap-1 px-1 rounded text-[10px] font-medium text-cyan-300 hover:text-cyan-200 hover:bg-white/10 transition-colors tabular-nums"
      >
        <Maximize2 className="w-3 h-3" />
        {pipScale}×
      </button>
    </div>
  );
}

export function StageCanvas({ sceneId, backdropUrl }) {
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
        <SceneContent sceneId={sceneId} backdropUrl={backdropUrl} />
        <Suspense fallback={null}>
          <Environment preset="studio" />
        </Suspense>
      </Canvas>
      <ShotPreviewFrame />
    </div>
  );
}
