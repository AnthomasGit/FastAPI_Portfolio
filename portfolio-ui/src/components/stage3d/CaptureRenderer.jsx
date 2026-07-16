import { useCallback } from 'react';
import { useThree } from '@react-three/fiber';
import { useStagingStore } from '@/stores/stagingStore';
import { api } from '@/lib/api';
import { useQueryClient } from '@tanstack/react-query';
import { getFormat } from './cameraFormats';
import { CaptureDepthContext } from './captureContext';
import * as THREE from 'three';

export function CaptureRenderer({ sceneId }) {
  const { gl, scene } = useThree();
  const queryClient = useQueryClient();
  const setIsCapturing = useStagingStore((s) => s.setIsCapturing);
  const isCapturing = useStagingStore((s) => s.isCapturing);
  const shotCamera = useStagingStore((s) => s.camera);

  const capture = useCallback(async () => {
    if (!shotCamera) return;
    setIsCapturing(true);

    const [width, height] = getFormat(shotCamera.format).capture;

    const target = new THREE.WebGLRenderTarget(width, height, {
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      format: THREE.RGBAFormat,
    });

    const depthMaterial = new THREE.MeshDepthMaterial({
      depthPacking: THREE.RGBADepthPacking,
    });

    const backdropMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff });

    const shotCam = new THREE.PerspectiveCamera(
      shotCamera.fov || 45,
      width / height,
      0.1,
      100
    );
    shotCam.position.set(
      shotCamera.position[0],
      shotCamera.position[1],
      shotCamera.position[2]
    );
    const targetPos = shotCamera.target || [0, 0, 0];
    shotCam.lookAt(targetPos[0], targetPos[1], targetPos[2]);
    shotCam.updateMatrixWorld();

    const originalMaterials = [];
    scene.traverse((child) => {
      if (child.isMesh) {
        originalMaterials.push({ mesh: child, material: child.material });
        if (child.userData?.isBackdrop) {
          child.material = backdropMaterial;
        } else {
          child.material = depthMaterial;
        }
      }
    });

    gl.setRenderTarget(target);
    gl.setClearColor(0xffffff, 1);
    gl.clear(true, true, true);
    gl.render(scene, shotCam);

    originalMaterials.forEach(({ mesh, material }) => {
      mesh.material = material;
    });

    gl.setRenderTarget(null);

    const pixelData = new Uint8Array(width * height * 4);
    gl.readRenderTargetPixels(target, 0, 0, width, height, pixelData);

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    const imageData = ctx.createImageData(width, height);
    imageData.data.set(pixelData);
    ctx.putImageData(imageData, 0, 0);

    target.dispose();
    depthMaterial.dispose();
    backdropMaterial.dispose();

    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, 'image/png')
    );

    try {
      await api.createCapture(sceneId, {
        depthMap: blob,
        camera: shotCamera,
        width,
        height,
      });
      queryClient.invalidateQueries({ queryKey: ['captures', sceneId] });
    } catch (e) {
      console.error('Capture upload failed', e);
    }

    setIsCapturing(false);
  }, [shotCamera, gl, scene, sceneId, queryClient, setIsCapturing]);

  return <CaptureDepthContext.Provider value={{ capture, isCapturing }} />;
}
