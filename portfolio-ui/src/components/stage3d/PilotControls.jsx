import { useEffect, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { useStagingStore } from '@/stores/stagingStore';
import { pilotState, seedFromCamera, commitPose, forwardVector } from './pilotState';

const MOVE_SPEED = 3;    // units/s
const TURN_SPEED = 0.5;  // rad/s — slow enough for fine framing
const FAST_MULT = 3;     // fast mode (toggled with Shift)
const MAX_PITCH = (89 * Math.PI) / 180;

const KEY_MAP = {
  w: 'w', a: 'a', s: 's', d: 'd', q: 'q', e: 'e',
  arrowleft: 'left', arrowright: 'right', arrowup: 'up', arrowdown: 'down',
};

function isEditable(t) {
  return (
    t instanceof HTMLElement &&
    (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
  );
}

// Keyboard flight for the shot camera while pilotMode is on. Mutates the shared
// pilotState at frame rate (no store writes); commits the final pose to the
// staging once, when the mode exits.
export function PilotControls() {
  const pilotMode = useStagingStore((s) => s.pilotMode);
  const setPilotMode = useStagingStore((s) => s.setPilotMode);
  const updateShotCamera = useStagingStore((s) => s.updateShotCamera);
  const keysRef = useRef(new Set());

  useEffect(() => {
    if (!pilotMode) return;

    seedFromCamera(useStagingStore.getState().camera);
    const keys = keysRef.current;
    keys.clear();

    const onKeyDown = (e) => {
      if (isEditable(e.target)) return;
      if (e.key === 'Escape' || e.key === 'Enter') {
        setPilotMode(false);
        return;
      }
      const k = KEY_MAP[e.key.toLowerCase()];
      if (k) {
        e.preventDefault();
        keys.add(k);
      }
    };
    const onKeyUp = (e) => {
      const k = KEY_MAP[e.key.toLowerCase()];
      if (k) keys.delete(k);
    };
    // Dropping focus (alt-tab) would strand held keys — clear on blur.
    const onBlur = () => keys.clear();

    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', onBlur);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      window.removeEventListener('blur', onBlur);
      keys.clear();
      updateShotCamera(commitPose());
    };
  }, [pilotMode, setPilotMode, updateShotCamera]);

  useFrame((_, delta) => {
    if (!pilotState.active) return;
    const keys = keysRef.current;
    if (keys.size === 0) return;

    const turn = TURN_SPEED * delta;
    if (keys.has('left')) pilotState.yaw += turn;
    if (keys.has('right')) pilotState.yaw -= turn;
    if (keys.has('up')) pilotState.pitch = Math.min(MAX_PITCH, pilotState.pitch + turn);
    if (keys.has('down')) pilotState.pitch = Math.max(-MAX_PITCH, pilotState.pitch - turn);

    const fast = useStagingStore.getState().fastMode;
    const speed = MOVE_SPEED * (fast ? FAST_MULT : 1) * delta;
    const [fx, fy, fz] = forwardVector(pilotState.yaw, pilotState.pitch);
    const rx = Math.cos(pilotState.yaw);
    const rz = -Math.sin(pilotState.yaw);
    const p = pilotState.pos;

    if (keys.has('w')) { p[0] += fx * speed; p[1] += fy * speed; p[2] += fz * speed; }
    if (keys.has('s')) { p[0] -= fx * speed; p[1] -= fy * speed; p[2] -= fz * speed; }
    if (keys.has('d')) { p[0] += rx * speed; p[2] += rz * speed; }
    if (keys.has('a')) { p[0] -= rx * speed; p[2] -= rz * speed; }
    if (keys.has('e')) p[1] += speed;
    if (keys.has('q')) p[1] -= speed;
  });

  return null;
}
