import { useRef, useMemo, useCallback, useEffect } from 'react';
import { useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useStagingStore } from '@/stores/stagingStore';
import * as THREE from 'three';

export function CameraRig() {
  const orbitRef = useRef();
  const appliedVersionRef = useRef(0);
  const get = useThree((s) => s.get);
  const camera = useStagingStore((s) => s.camera);
  const setCamera = useStagingStore((s) => s.setCamera);
  const hydrationVersion = useStagingStore((s) => s.hydrationVersion);

  // Apply the stored camera to the live view whenever the store is hydrated
  // from the server (initial load, save restore) — never on user orbit commits
  useEffect(() => {
    if (appliedVersionRef.current === hydrationVersion) return;
    if (!orbitRef.current) return;
    appliedVersionRef.current = hydrationVersion;
    if (!camera) return;
    const glCamera = get().camera;
    if (camera.position) glCamera.position.set(...camera.position);
    if (camera.target) orbitRef.current.target.set(...camera.target);
    if (camera.fov) {
      glCamera.fov = camera.fov;
      glCamera.updateProjectionMatrix();
    }
    orbitRef.current.update();
  }, [hydrationVersion, camera, get]);

  const shotCamera = useMemo(() => {
    const cam = new THREE.PerspectiveCamera(
      camera?.fov || 45,
      camera?.aspect || 16 / 9,
      0.1,
      100
    );
    if (camera?.position) {
      cam.position.set(
        camera.position[0],
        camera.position[1],
        camera.position[2]
      );
    }
    if (camera?.target) {
      cam.lookAt(
        camera.target[0],
        camera.target[1],
        camera.target[2]
      );
    }
    return cam;
  }, [camera]);

  const commitCamera = useCallback(() => {
    if (!orbitRef.current) return;
    const glCamera = get().camera;
    const pos = glCamera.position;
    const target = orbitRef.current.target;
    setCamera({
      position: [pos.x, pos.y, pos.z],
      target: [target.x, target.y, target.z],
      fov: glCamera.fov,
      aspect: glCamera.aspect,
    });
  }, [get, setCamera]);

  return (
    <>
      <OrbitControls
        ref={orbitRef}
        makeDefault
        enableDamping
        dampingFactor={0.1}
        minDistance={1}
        maxDistance={50}
        onEnd={commitCamera}
      />
      {shotCamera && (
        <group>
          <primitive object={shotCamera} />
        </group>
      )}
    </>
  );
}
