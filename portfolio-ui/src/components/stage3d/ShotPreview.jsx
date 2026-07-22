import { useRef, useEffect } from 'react';
import { useFrame } from '@react-three/fiber';
import { useStagingStore } from '@/stores/stagingStore';
import { getFormat, pipSize, gateRect, PIP_MARGIN } from './cameraFormats';
import { hideForShot } from './sceneFilters';
import { pilotState, forwardVector } from './pilotState';
import * as THREE from 'three';

// Owns the render loop (useFrame priority > 0 disables R3F auto-render).
// Normal mode: full-frame navigation view + the shot camera in a bottom-right
// scissored corner. Pilot mode: through-the-lens — black canvas with the live
// shot camera rendered into a centered, format-aspect gate.
export function ShotPreview() {
  const camera = useStagingStore((s) => s.camera);
  const pipScale = useStagingStore((s) => s.pipScale);
  const shotCamRef = useRef(null);
  const clearColorRef = useRef(null);

  useEffect(() => {
    shotCamRef.current = new THREE.PerspectiveCamera();
    clearColorRef.current = new THREE.Color();
  }, []);

  useFrame((state) => {
    const { gl, scene, camera: navCam, size } = state;
    const shotCam = shotCamRef.current;
    const piloting = pilotState.active && useStagingStore.getState().pilotMode;

    if (!piloting) {
      // ── Normal: nav view full-frame + corner PiP ─────────────────────────
      gl.setScissorTest(false);
      gl.setViewport(0, 0, size.width, size.height);
      gl.render(scene, navCam);

      if (!camera || !shotCam) return;

      const aspect = getFormat(camera.format).aspect;
      const { pw, ph } = pipSize(aspect, pipScale);

      shotCam.fov = camera.fov || 45;
      shotCam.aspect = aspect;
      shotCam.near = 0.1;
      shotCam.far = 100;
      if (camera.position) shotCam.position.set(...camera.position);
      if (camera.target) shotCam.lookAt(...camera.target);
      shotCam.updateProjectionMatrix();
      shotCam.updateMatrixWorld(true);

      const restore = hideForShot(scene);

      const x = size.width - pw - PIP_MARGIN; // WebGL origin is bottom-left
      const y = PIP_MARGIN;
      gl.setScissorTest(true);
      gl.setViewport(x, y, pw, ph);
      gl.setScissor(x, y, pw, ph);
      gl.render(scene, shotCam);
      gl.setScissorTest(false);

      restore();
      return;
    }

    // ── Pilot: through the lens ──────────────────────────────────────────
    if (!shotCam) return;

    const aspect = getFormat(camera?.format).aspect;
    const { x, y, gw, gh } = gateRect(aspect, size.width, size.height);

    shotCam.fov = camera?.fov || 45;
    shotCam.aspect = aspect;
    shotCam.near = 0.1;
    shotCam.far = 100;
    const p = pilotState.pos;
    const [fx, fy, fz] = forwardVector(pilotState.yaw, pilotState.pitch);
    shotCam.position.set(p[0], p[1], p[2]);
    shotCam.lookAt(p[0] + fx, p[1] + fy, p[2] + fz);
    shotCam.updateProjectionMatrix();
    shotCam.updateMatrixWorld(true);

    // Black out everything, then render only the gate.
    const prevClear = clearColorRef.current;
    gl.getClearColor(prevClear);
    const prevAlpha = gl.getClearAlpha();
    gl.setScissorTest(false);
    gl.setViewport(0, 0, size.width, size.height);
    gl.setClearColor(0x000000, 1);
    gl.clear(true, true, true);

    const restore = hideForShot(scene);

    gl.setScissorTest(true);
    gl.setViewport(x, y, gw, gh);
    gl.setScissor(x, y, gw, gh);
    gl.render(scene, shotCam);
    gl.setScissorTest(false);

    restore();
    gl.setClearColor(prevClear, prevAlpha);
  }, 1);

  return null;
}
