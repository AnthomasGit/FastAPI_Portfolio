import { useRef, useEffect } from 'react';
import { useFrame } from '@react-three/fiber';
import { useStagingStore } from '@/stores/stagingStore';
import { getFormat, pipSize, PIP_MARGIN } from './cameraFormats';
import * as THREE from 'three';

// Owns the render loop (useFrame priority > 0 disables R3F auto-render): draws
// the full-frame navigation view, then the shot camera into a bottom-right
// scissored corner. Two cameras, one scene.
export function ShotPreview() {
  const camera = useStagingStore((s) => s.camera);
  const shotCamRef = useRef(null);

  useEffect(() => {
    shotCamRef.current = new THREE.PerspectiveCamera();
  }, []);

  useFrame((state) => {
    const { gl, scene, camera: navCam, size } = state;
    const shotCam = shotCamRef.current;

    gl.setScissorTest(false);
    gl.setViewport(0, 0, size.width, size.height);
    gl.render(scene, navCam);

    if (!camera || !shotCam) return;

    const aspect = getFormat(camera.format).aspect;
    const { pw, ph } = pipSize(aspect);

    shotCam.fov = camera.fov || 45;
    shotCam.aspect = aspect;
    shotCam.near = 0.1;
    shotCam.far = 100;
    if (camera.position) shotCam.position.set(...camera.position);
    if (camera.target) shotCam.lookAt(...camera.target);
    shotCam.updateProjectionMatrix();
    shotCam.updateMatrixWorld(true);

    // Hide the shot frustum gizmo (and transform gizmos) inside its own preview.
    const hidden = [];
    scene.traverse((o) => {
      if ((o.userData?.hideInShot || o.isTransformControlsRoot) && o.visible) {
        o.visible = false;
        hidden.push(o);
      }
    });

    const x = size.width - pw - PIP_MARGIN; // WebGL origin is bottom-left
    const y = PIP_MARGIN;
    gl.setScissorTest(true);
    gl.setViewport(x, y, pw, ph);
    gl.setScissor(x, y, pw, ph);
    gl.render(scene, shotCam);
    gl.setScissorTest(false);

    hidden.forEach((o) => { o.visible = true; });
  }, 1);

  return null;
}
