import { useRef, useMemo } from 'react';
import { useThree, useFrame } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useStagingStore } from '@/stores/stagingStore';
import * as THREE from 'three';

export function CameraRig() {
  const orbitRef = useRef();
  const { camera: glCamera } = useThree();
  const camera = useStagingStore((s) => s.camera);
  const setCamera = useStagingStore((s) => s.setCamera);

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

  useFrame(() => {
    if (orbitRef.current) {
      const pos = glCamera.position;
      const target = orbitRef.current.target;
      setCamera({
        position: [pos.x, pos.y, pos.z],
        target: [target.x, target.y, target.z],
        fov: glCamera.fov,
        aspect: glCamera.aspect,
      });
    }
  });

  return (
    <>
      <OrbitControls
        ref={orbitRef}
        makeDefault
        enableDamping
        dampingFactor={0.1}
        minDistance={1}
        maxDistance={50}
      />
      {shotCamera && (
        <group>
          <primitive object={shotCamera} />
        </group>
      )}
    </>
  );
}
