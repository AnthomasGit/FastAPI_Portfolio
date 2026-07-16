import { useRef, useMemo, useCallback, useEffect } from 'react';
import { useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useStagingStore } from '@/stores/stagingStore';
import { getFormat } from './cameraFormats';
import * as THREE from 'three';

// Fixed, comfortable field of view for free navigation — independent of the
// shot camera's lens, so flying around an 85mm shot isn't claustrophobic.
const NAV_FOV = 50;

export function CameraRig() {
  const orbitRef = useRef();
  const appliedVersionRef = useRef(0);
  const get = useThree((s) => s.get);
  const camera = useStagingStore((s) => s.camera);
  const setNavPose = useStagingStore((s) => s.setNavPose);
  const hydrationVersion = useStagingStore((s) => s.hydrationVersion);

  // On hydrate (initial load / save restore) adopt the shot's position+target so
  // the first thing you see roughly matches the shot — but keep the nav fov.
  useEffect(() => {
    if (appliedVersionRef.current === hydrationVersion) return;
    if (!orbitRef.current) return;
    appliedVersionRef.current = hydrationVersion;
    const glCamera = get().camera;
    if (glCamera.fov !== NAV_FOV) {
      glCamera.fov = NAV_FOV;
      glCamera.updateProjectionMatrix();
    }
    if (camera?.position) glCamera.position.set(...camera.position);
    if (camera?.target) orbitRef.current.target.set(...camera.target);
    orbitRef.current.update();
    setNavPose({
      position: glCamera.position.toArray(),
      target: orbitRef.current.target.toArray(),
    });
  }, [hydrationVersion, camera, get, setNavPose]);

  // Frustum gizmo mirroring the shot camera (pose + lens + format aspect).
  // Rebuilt whenever the shot changes (infrequent) so the object is fully
  // configured at creation — no post-hoc mutation of a memoized value.
  const helper = useMemo(() => {
    const cam = new THREE.PerspectiveCamera(
      camera?.fov || 45,
      getFormat(camera?.format).aspect,
      0.1,
      12,
    );
    if (camera?.position) cam.position.set(...camera.position);
    if (camera?.target) cam.lookAt(...camera.target);
    cam.updateProjectionMatrix();
    cam.updateMatrixWorld(true);
    const h = new THREE.CameraHelper(cam);
    h.userData.hideInShot = true; // hide frustum inside its own preview
    return h;
  }, [camera]);

  useEffect(() => () => helper.dispose(), [helper]);

  const commitNavPose = useCallback(() => {
    if (!orbitRef.current) return;
    const glCamera = get().camera;
    setNavPose({
      position: glCamera.position.toArray(),
      target: orbitRef.current.target.toArray(),
    });
  }, [get, setNavPose]);

  return (
    <>
      <OrbitControls
        ref={orbitRef}
        makeDefault
        enableDamping
        dampingFactor={0.1}
        minDistance={1}
        maxDistance={50}
        onEnd={commitNavPose}
      />
      <primitive object={helper} />
    </>
  );
}
