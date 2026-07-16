import { useCallback, useEffect } from 'react';
import { useThree } from '@react-three/fiber';
import { useStagingStore } from '@/stores/stagingStore';
import { api } from '@/lib/api';
import { useQueryClient } from '@tanstack/react-query';
import { getFormat } from './cameraFormats';
import * as THREE from 'three';

export function CaptureRenderer({ sceneId }) {
  const gl = useThree((s) => s.gl);
  const getThree = useThree((s) => s.get);
  const queryClient = useQueryClient();
  const setIsCapturing = useStagingStore((s) => s.setIsCapturing);
  const setCaptureFn = useStagingStore((s) => s.setCaptureFn);
  const shotCamera = useStagingStore((s) => s.camera);

  const capture = useCallback(async () => {
    if (!shotCamera || !sceneId) return;
    setIsCapturing(true);

    const scene = getThree().scene;
    const [width, height] = getFormat(shotCamera.format).capture;
    const target = new THREE.WebGLRenderTarget(width, height, {
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      format: THREE.RGBAFormat,
    });

    const shotCam = new THREE.PerspectiveCamera(shotCamera.fov || 45, width / height, 0.1, 100);
    shotCam.position.set(...(shotCamera.position || [0, 0, 0]));
    shotCam.lookAt(...(shotCamera.target || [0, 0, 0]));
    shotCam.updateMatrixWorld();

    // Linearized, inverted depth (near = bright, far = dark) normalized over a
    // range keyed to how far the camera sits from its target, so content has
    // usable contrast instead of saturating white the way raw perspective depth
    // does. Grayscale RGB — a viewable, ControlNet-style depth map.
    const camDist = shotCam.position.distanceTo(
      new THREE.Vector3(...(shotCamera.target || [0, 0, 0]))
    );
    const depthMaterial = new THREE.ShaderMaterial({
      side: THREE.DoubleSide,
      uniforms: { uNear: { value: 0.1 }, uFar: { value: Math.max(camDist * 2, 1.1) } },
      vertexShader: `
        varying float vViewDepth;
        void main() {
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          vViewDepth = -mv.z;
          gl_Position = projectionMatrix * mv;
        }
      `,
      fragmentShader: `
        uniform float uNear;
        uniform float uFar;
        varying float vViewDepth;
        void main() {
          float d = clamp((vViewDepth - uNear) / (uFar - uNear), 0.0, 1.0);
          // Gamma lift (<1) brightens the midtones while keeping near=bright,
          // far=dark ordering.
          float b = pow(1.0 - d, 0.5);
          gl_FragColor = vec4(vec3(b), 1.0);
        }
      `,
    });

    // Records what we changed so finally can always put it back — a throw mid
    // capture must never leave a swapped material/visibility behind, which would
    // crash the render loop or corrupt the live view.
    const restore = [];
    const prevBackground = scene.background;

    try {
      // Black "far" background: null out the scene's colored background so the
      // black clear shows through as maximum depth.
      scene.background = null;

      scene.traverse((obj) => {
        // Exclude the backdrop (a flat photo plane would read as a false wall),
        // gizmos/helpers, and drei's infinite Grid from the depth pass.
        const isGizmo = obj.userData?.hideInShot || obj.isTransformControlsRoot;
        const isGrid = obj.isMesh && obj.material && 'worldCamProjPosition' in obj.material;
        const isBackdrop = obj.userData?.isBackdrop;
        if (isGizmo || isGrid || isBackdrop) {
          restore.push({ obj, visible: obj.visible });
          obj.visible = false;
        } else if (obj.isMesh) {
          restore.push({ obj, material: obj.material });
          obj.material = depthMaterial;
        }
      });

      gl.setRenderTarget(target);
      gl.setClearColor(0x000000, 1);
      gl.clear(true, true, true);
      gl.render(scene, shotCam);

      const pixelData = new Uint8Array(width * height * 4);
      gl.readRenderTargetPixels(target, 0, 0, width, height, pixelData);

      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');
      const imageData = ctx.createImageData(width, height);
      imageData.data.set(pixelData);
      ctx.putImageData(imageData, 0, 0);

      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));

      await api.createCapture(sceneId, { depthMap: blob, camera: shotCamera, width, height });
      queryClient.invalidateQueries({ queryKey: ['captures', sceneId] });
    } catch (e) {
      console.error('Capture failed', e);
    } finally {
      restore.forEach(({ obj, material, visible }) => {
        if (material !== undefined) obj.material = material;
        if (visible !== undefined) obj.visible = visible;
      });
      scene.background = prevBackground;
      gl.setRenderTarget(null);
      target.dispose();
      depthMaterial.dispose();
      setIsCapturing(false);
    }
  }, [shotCamera, gl, getThree, sceneId, queryClient, setIsCapturing]);

  // Publish the capture fn to the store so the toolbar (which lives outside the
  // Canvas, across the R3F reconciler boundary that React context can't cross)
  // can trigger it.
  useEffect(() => {
    setCaptureFn(capture);
    return () => setCaptureFn(null);
  }, [capture, setCaptureFn]);

  return null;
}
