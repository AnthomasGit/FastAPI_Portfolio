import { useRef, useMemo, useCallback, useEffect } from 'react';
import { useThree, useFrame } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useStagingStore } from '@/stores/stagingStore';
import { getFormat } from './cameraFormats';
import * as THREE from 'three';

// Fixed, comfortable field of view for free navigation — independent of the
// shot camera's lens, so flying around an 85mm shot isn't claustrophobic.
const NAV_FOV = 50;

const NAV_MOVE_SPEED = 4; // units/s (fast mode = 3x, toggled with Shift)
const NAV_KEYS = { w: 'w', a: 'a', s: 's', d: 'd', q: 'q', e: 'e' };

function isEditable(t) {
  return (
    t instanceof HTMLElement &&
    (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
  );
}

export function CameraRig() {
  const orbitRef = useRef();
  const appliedVersionRef = useRef(0);
  const get = useThree((s) => s.get);
  const camera = useStagingStore((s) => s.camera);
  const setNavPose = useStagingStore((s) => s.setNavPose);
  const pilotMode = useStagingStore((s) => s.pilotMode);
  const setPilotMode = useStagingStore((s) => s.setPilotMode);
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

  // Clickable camera body at the shot pose — the entry point for pilot mode
  // (the line-based CameraHelper itself can't be raycast reliably).
  const bodyPose = useMemo(() => {
    if (!camera?.position) return null;
    const o = new THREE.Object3D();
    o.position.set(...camera.position);
    o.lookAt(...(camera.target || [0, 0, 0]));
    return { position: [...camera.position], quaternion: o.quaternion.clone() };
  }, [camera]);

  const commitNavPose = useCallback(() => {
    if (!orbitRef.current) return;
    const glCamera = get().camera;
    setNavPose({
      position: glCamera.position.toArray(),
      target: orbitRef.current.target.toArray(),
    });
  }, [get, setNavPose]);

  // WASD/QE fly for the navigation view (pilot mode has its own controls).
  // Camera and orbit target translate together so orbiting keeps working
  // around the moved focus point.
  const navKeysRef = useRef(new Set());

  useEffect(() => {
    if (pilotMode) {
      navKeysRef.current.clear();
      return;
    }
    const keys = navKeysRef.current;
    const onKeyDown = (e) => {
      if (isEditable(e.target)) return;
      const k = NAV_KEYS[e.key.toLowerCase()];
      if (k) keys.add(k);
    };
    const onKeyUp = (e) => {
      const k = NAV_KEYS[e.key.toLowerCase()];
      if (k) {
        keys.delete(k);
        if (keys.size === 0) commitNavPose();
      }
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
  }, [pilotMode, commitNavPose]);

  const navForward = useMemo(() => new THREE.Vector3(), []);
  const navRight = useMemo(() => new THREE.Vector3(), []);

  useFrame((_, delta) => {
    const keys = navKeysRef.current;
    if (keys.size === 0 || !orbitRef.current || pilotMode) return;
    // With a selection active, WASD moves the selected object instead
    // (AssetFlyControls) — the camera stays put.
    if (useStagingStore.getState().selection) return;

    const glCamera = get().camera;
    const speed = NAV_MOVE_SPEED * (useStagingStore.getState().fastMode ? 3 : 1) * delta;

    glCamera.getWorldDirection(navForward);
    navRight.crossVectors(navForward, glCamera.up).normalize();

    const step = new THREE.Vector3();
    if (keys.has('w')) step.addScaledVector(navForward, speed);
    if (keys.has('s')) step.addScaledVector(navForward, -speed);
    if (keys.has('d')) step.addScaledVector(navRight, speed);
    if (keys.has('a')) step.addScaledVector(navRight, -speed);
    if (keys.has('e')) step.y += speed;
    if (keys.has('q')) step.y -= speed;

    glCamera.position.add(step);
    orbitRef.current.target.add(step);
    orbitRef.current.update();
  });

  return (
    <>
      <OrbitControls
        ref={orbitRef}
        makeDefault
        enabled={!pilotMode}
        enableDamping
        dampingFactor={0.1}
        minDistance={1}
        maxDistance={50}
        onEnd={commitNavPose}
      />
      <primitive object={helper} visible={!pilotMode} />
      {bodyPose && !pilotMode && (
        <group position={bodyPose.position} quaternion={bodyPose.quaternion}>
          <mesh
            rotation={[Math.PI / 2, 0, 0]}
            userData={{ hideInShot: true }}
            onClick={(e) => {
              e.stopPropagation();
              setPilotMode(true);
            }}
            onPointerOver={() => { document.body.style.cursor = 'pointer'; }}
            onPointerOut={() => { document.body.style.cursor = 'auto'; }}
          >
            <coneGeometry args={[0.16, 0.36, 12]} />
            <meshBasicMaterial color="#22d3ee" wireframe />
          </mesh>
        </group>
      )}
    </>
  );
}
