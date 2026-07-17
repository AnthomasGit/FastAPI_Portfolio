import { useEffect, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { useStagingStore } from '@/stores/stagingStore';
import * as THREE from 'three';

const MOVE_SPEED = 3; // units/s (fast mode = 3x, toggled with Shift)
const KEYS = { w: 'w', a: 'a', s: 's', d: 'd', q: 'q', e: 'e' };

function isEditable(t) {
  return (
    t instanceof HTMLElement &&
    (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
  );
}

// WASD/QE nudges the selected object (asset, blockout, or backdrop) relative to
// the viewing direction: W/S along the camera's heading projected onto the
// ground plane, A/D strafe, Q/E vertical. Active only while something is
// selected (otherwise the same keys fly the nav camera in CameraRig).
export function AssetFlyControls() {
  const get = useThree((s) => s.get);
  const moveSelected = useStagingStore((s) => s.moveSelected);
  const keysRef = useRef(new Set());
  const forwardRef = useRef(new THREE.Vector3());

  useEffect(() => {
    const keys = keysRef.current;
    const onKeyDown = (e) => {
      if (isEditable(e.target)) return;
      const k = KEYS[e.key.toLowerCase()];
      if (k) keys.add(k);
    };
    const onKeyUp = (e) => {
      const k = KEYS[e.key.toLowerCase()];
      if (k) keys.delete(k);
    };
    const onBlur = () => keys.clear();
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', onBlur);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      window.removeEventListener('blur', onBlur);
      keys.clear();
    };
  }, []);

  useFrame((_, delta) => {
    const keys = keysRef.current;
    if (keys.size === 0) return;
    const { selection, pilotMode, fastMode } = useStagingStore.getState();
    if (!selection || pilotMode) return;

    const speed = MOVE_SPEED * (fastMode ? 3 : 1) * delta;

    // Camera heading on the ground plane — movement follows the view.
    const fwd = forwardRef.current;
    get().camera.getWorldDirection(fwd);
    fwd.y = 0;
    if (fwd.lengthSq() < 1e-6) fwd.set(0, 0, -1);
    fwd.normalize();
    const rx = -fwd.z;
    const rz = fwd.x;

    let dx = 0, dy = 0, dz = 0;
    if (keys.has('w')) { dx += fwd.x * speed; dz += fwd.z * speed; }
    if (keys.has('s')) { dx -= fwd.x * speed; dz -= fwd.z * speed; }
    if (keys.has('d')) { dx += rx * speed; dz += rz * speed; }
    if (keys.has('a')) { dx -= rx * speed; dz -= rz * speed; }
    if (keys.has('e')) dy += speed;
    if (keys.has('q')) dy -= speed;

    if (dx || dy || dz) moveSelected([dx, dy, dz]);
  });

  return null;
}
