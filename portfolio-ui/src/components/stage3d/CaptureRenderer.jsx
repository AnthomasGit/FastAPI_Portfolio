import { useCallback, useEffect } from 'react';
import { useThree } from '@react-three/fiber';
import { useStagingStore } from '@/stores/stagingStore';
import { api } from '@/lib/api';
import { useQueryClient } from '@tanstack/react-query';
import { getFormat } from './cameraFormats';
import { isGizmoObject, isGridMesh, isStagingObject } from './sceneFilters';
import { pilotState, forwardVector } from './pilotState';
import * as THREE from 'three';

// Synchronous readback of a render target's pixels (must run in the same
// synchronous block as the render so the frame loop can't interleave).
function readTargetPixels(gl, target, width, height) {
  const pixelData = new Uint8Array(width * height * 4);
  gl.readRenderTargetPixels(target, 0, 0, width, height, pixelData);
  return pixelData;
}

// Encode raw pixels to a PNG blob, flipping rows: WebGL's readback origin is
// bottom-left while canvas ImageData is top-down — without the flip every
// capture comes out vertically mirrored. Async (toBlob); safe to run after all
// GPU passes are done.
async function pixelsToBlob(pixelData, width, height) {
  const rowBytes = width * 4;
  const flipped = new Uint8ClampedArray(pixelData.length);
  for (let y = 0; y < height; y++) {
    const src = y * rowBytes;
    const dst = (height - 1 - y) * rowBytes;
    flipped.set(pixelData.subarray(src, src + rowBytes), dst);
  }

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  ctx.putImageData(new ImageData(flipped, width, height), 0, 0);
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
}

// Swap materials for a conditioning pass: hides editor chrome + backdrop and
// swaps every remaining mesh's material via materialFor(mesh). Skips everything
// inside an excluded subtree — hidden objects still get updateMatrixWorld, and
// TransformControls' gizmo handles read material.color there, which conditioning
// materials lack. Changes are recorded into `restore` for the caller's finally.
function swapMaterials(scene, restore, materialFor) {
  const excludedRoots = new Set();
  scene.traverse((obj) => {
    if (isGizmoObject(obj) || isGridMesh(obj) || obj.userData?.isBackdrop) {
      excludedRoots.add(obj);
      restore.push({ obj, visible: obj.visible });
      obj.visible = false;
      return;
    }
    for (let p = obj.parent; p; p = p.parent) {
      if (excludedRoots.has(p)) return;
    }
    if (obj.isMesh) {
      restore.push({ obj, material: obj.material });
      obj.material = materialFor(obj);
    }
  });
}

// Top-level ancestor of a mesh (direct child of the scene) — one placed asset,
// blockout item, etc. is one subtree, and therefore one segmentation region.
function segmentRoot(obj, scene) {
  let node = obj;
  while (node.parent && node.parent !== scene) node = node.parent;
  return node;
}

// Distinct, stable flat color per segment root (uuid hash → hue).
function segmentColor(uuid) {
  let hash = 0;
  for (let i = 0; i < uuid.length; i++) {
    hash = (hash * 31 + uuid.charCodeAt(i)) >>> 0;
  }
  const hue = hash % 360;
  return new THREE.Color().setHSL(hue / 360, 0.9, 0.55);
}

// ── FBO-derived depth/normal maps ────────────────────────────────────────────
// Scene-material replacement (override or per-mesh swap) with varying-dependent
// materials rendered geometry but produced zero fragments on the user's
// GPU/driver (401k triangles submitted, black output — while uniform-colored
// and real materials worked). So depth/normal are instead DERIVED from the
// depth buffer of a real-materials render: the scene draws once into an FBO
// with a DepthTexture attached (the proven pipeline), then fullscreen-quad
// post passes sample that texture to produce the maps.

const quadCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
const quadMesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2));
const quadScene = new THREE.Scene();
quadScene.add(quadMesh);

const QUAD_VERT = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`;

// Shared GLSL: nonlinear [0,1] depth-buffer sample → view-space distance.
const VIEWZ_GLSL = `
  uniform sampler2D tDepth;
  uniform float cameraNear;
  uniform float cameraFar;
  float viewZAt(vec2 uv) {
    float z = texture2D(tDepth, uv).x;
    return (cameraNear * cameraFar) / (cameraFar - z * (cameraFar - cameraNear));
  }
`;

// Pack pass: encodes viewZ / cameraFar as 16-bit fixed point in R (high byte)
// and G (low byte), so the CPU can scan the frame's actual depth band. The
// display range is derived from content, not from the (synthetic) camera
// target — a telephoto shot 37 units from its subject must not clamp black.
const packDepthMaterial = new THREE.ShaderMaterial({
  uniforms: {
    tDepth: { value: null },
    cameraNear: { value: 0.1 },
    cameraFar: { value: 100 },
  },
  vertexShader: QUAD_VERT,
  fragmentShader: `
    ${VIEWZ_GLSL}
    varying vec2 vUv;
    void main() {
      float v = clamp(viewZAt(vUv) / cameraFar, 0.0, 1.0);
      float hi = floor(v * 255.0) / 255.0;
      float lo = fract(v * 255.0);
      gl_FragColor = vec4(hi, lo, 0.0, 1.0);
    }
  `,
});

// Depth map: linearized, inverted (near = bright, far = dark), normalized over
// the frame's measured content range (per-frame relative depth, the
// MiDaS/ControlNet convention). Geometry brightness floors at 0.12 so the
// farthest content stays above the black background (depth = 1).
const depthViewMaterial = new THREE.ShaderMaterial({
  uniforms: {
    tDepth: { value: null },
    cameraNear: { value: 0.1 },
    cameraFar: { value: 100 },
    uRangeNear: { value: 0.1 },
    uRangeFar: { value: 10 },
  },
  vertexShader: QUAD_VERT,
  fragmentShader: `
    ${VIEWZ_GLSL}
    uniform float uRangeNear;
    uniform float uRangeFar;
    varying vec2 vUv;
    void main() {
      float z = texture2D(tDepth, vUv).x;
      if (z >= 0.9999) { gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); return; }
      float viewZ = viewZAt(vUv);
      float d = clamp((viewZ - uRangeNear) / (uRangeFar - uRangeNear), 0.0, 1.0);
      float b = mix(0.12, 1.0, pow(1.0 - d, 0.5));
      gl_FragColor = vec4(vec3(b), 1.0);
    }
  `,
});

// Normal map: screen-space normals reconstructed from depth via neighboring
// view-space positions (ControlNet-normal style). Background stays black.
const normalViewMaterial = new THREE.ShaderMaterial({
  uniforms: {
    tDepth: { value: null },
    cameraNear: { value: 0.1 },
    cameraFar: { value: 100 },
    uTexel: { value: new THREE.Vector2(1 / 1024, 1 / 576) },
    uTanHalfFov: { value: new THREE.Vector2(1, 1) }, // (tanHalfFovX, tanHalfFovY)
  },
  vertexShader: QUAD_VERT,
  fragmentShader: `
    ${VIEWZ_GLSL}
    uniform vec2 uTexel;
    uniform vec2 uTanHalfFov;
    varying vec2 vUv;
    vec3 viewPosAt(vec2 uv) {
      float vz = viewZAt(uv);
      vec2 ndc = uv * 2.0 - 1.0;
      return vec3(ndc.x * vz * uTanHalfFov.x, ndc.y * vz * uTanHalfFov.y, -vz);
    }
    void main() {
      float z = texture2D(tDepth, vUv).x;
      if (z >= 0.9999) { gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); return; }
      vec3 p = viewPosAt(vUv);
      vec3 px = viewPosAt(vUv + vec2(uTexel.x, 0.0));
      vec3 py = viewPosAt(vUv + vec2(0.0, uTexel.y));
      vec3 n = normalize(cross(px - p, py - p));
      // Face the camera (+Z toward viewer in view space).
      if (n.z < 0.0) n = -n;
      gl_FragColor = vec4(n * 0.5 + 0.5, 1.0);
    }
  `,
});

export function CaptureRenderer({ sceneId }) {
  const gl = useThree((s) => s.gl);
  const getThree = useThree((s) => s.get);
  const queryClient = useQueryClient();
  const setIsCapturing = useStagingStore((s) => s.setIsCapturing);
  const setCaptureFn = useStagingStore((s) => s.setCaptureFn);
  const shotCamera = useStagingStore((s) => s.camera);

  // Pre-warm the quad materials' shader programs at mount (a 1×1 offscreen
  // render each), so no program is first-linked inside the capture click tick.
  useEffect(() => {
    const tiny = new THREE.WebGLRenderTarget(1, 1);
    try {
      for (const mat of [depthViewMaterial, normalViewMaterial, packDepthMaterial]) {
        quadMesh.material = mat;
        gl.setRenderTarget(tiny);
        gl.render(quadScene, quadCamera);
      }
    } finally {
      gl.setRenderTarget(null);
      tiny.dispose();
    }
  }, [gl]);

  const capture = useCallback(async () => {
    if (!shotCamera || !sceneId) return;
    setIsCapturing(true);

    const scene = getThree().scene;
    const captureMode = useStagingStore.getState().captureMode;
    const [width, height] = getFormat(shotCamera.format).capture;

    // One target reused by all conditioning-map passes (pixels are read back
    // synchronously before the next pass renders).
    const mapTarget = new THREE.WebGLRenderTarget(width, height, {
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      format: THREE.RGBAFormat,
    });
    // SRGB colorSpace so the beauty readback matches what's on screen instead
    // of coming out as washed-out linear values.
    const colorTarget = new THREE.WebGLRenderTarget(width, height, {
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      format: THREE.RGBAFormat,
      colorSpace: THREE.SRGBColorSpace,
    });

    // Depth-source FBO: real-materials render writes its depth buffer into this
    // texture; the quad passes below derive the maps from it.
    const depthTexture = new THREE.DepthTexture(width, height);
    const sourceTarget = new THREE.WebGLRenderTarget(width, height, {
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      format: THREE.RGBAFormat,
      depthTexture,
    });

    const CAM_NEAR = 0.1;
    const CAM_FAR = 100;
    const fov = shotCamera.fov || 45;
    const aspect = width / height;
    const shotCam = new THREE.PerspectiveCamera(fov, aspect, CAM_NEAR, CAM_FAR);
    // While piloting, the store `camera` is stale (committed only on pilot exit),
    // so derive the live pose from pilotState — same source ShotPreview renders.
    const piloting = pilotState.active && useStagingStore.getState().pilotMode;
    let camPosition, camTarget;
    if (piloting) {
      const p = pilotState.pos;
      const [fx, fy, fz] = forwardVector(pilotState.yaw, pilotState.pitch);
      const d = pilotState.targetDistance;
      camPosition = [p[0], p[1], p[2]];
      camTarget = [p[0] + fx * d, p[1] + fy * d, p[2] + fz * d];
    } else {
      camPosition = shotCamera.position || [0, 0, 0];
      camTarget = shotCamera.target || [0, 0, 0];
    }
    shotCam.position.set(...camPosition);
    shotCam.lookAt(...camTarget);
    shotCam.updateMatrixWorld();

    depthViewMaterial.uniforms.tDepth.value = depthTexture;
    depthViewMaterial.uniforms.cameraNear.value = CAM_NEAR;
    depthViewMaterial.uniforms.cameraFar.value = CAM_FAR;

    packDepthMaterial.uniforms.tDepth.value = depthTexture;
    packDepthMaterial.uniforms.cameraNear.value = CAM_NEAR;
    packDepthMaterial.uniforms.cameraFar.value = CAM_FAR;

    const tanHalfFovY = Math.tan(THREE.MathUtils.degToRad(fov) / 2);
    normalViewMaterial.uniforms.tDepth.value = depthTexture;
    normalViewMaterial.uniforms.cameraNear.value = CAM_NEAR;
    normalViewMaterial.uniforms.cameraFar.value = CAM_FAR;
    normalViewMaterial.uniforms.uTexel.value.set(1 / width, 1 / height);
    normalViewMaterial.uniforms.uTanHalfFov.value.set(tanHalfFovY * aspect, tanHalfFovY);

    // Records what we changed so finally can always put it back — a throw mid
    // capture must never leave a swapped material/visibility behind, which would
    // crash the render loop or corrupt the live view.
    const restore = [];
    const prevBackground = scene.background;
    const segMaterials = new Map(); // segment-root uuid → MeshBasicMaterial

    const restoreAll = () => {
      restore.forEach(({ obj, material, visible }) => {
        if (material !== undefined) obj.material = material;
        if (visible !== undefined) obj.visible = visible;
      });
      restore.length = 0;
    };

    // Fullscreen-quad post pass sampling the source render's depth texture —
    // no scene materials involved at all.
    const runQuadPass = (material) => {
      quadMesh.material = material;
      gl.setRenderTarget(mapTarget);
      gl.setClearColor(0x000000, 1);
      gl.clear(true, true, true);
      gl.render(quadScene, quadCamera);
      return readTargetPixels(gl, mapTarget, width, height);
    };

    // Segmentation needs per-object materials, so it keeps the per-mesh swap.
    const runMapPass = (materialFor) => {
      swapMaterials(scene, restore, materialFor);
      gl.setRenderTarget(mapTarget);
      gl.setClearColor(0x000000, 1);
      gl.clear(true, true, true);
      gl.render(scene, shotCam);
      const pixels = readTargetPixels(gl, mapTarget, width, height);
      restoreAll();
      return pixels;
    };

    try {
      // ── Conditioning maps (all GPU work synchronous, no awaits) ──────────
      gl.setScissorTest(false);
      scene.background = null;

      // Depth-source render: REAL materials (the proven pipeline), with editor
      // chrome + backdrop hidden (a flat photo plane would read as a false
      // wall — LLD risk R5). Its depth buffer feeds the quad passes.
      scene.traverse((obj) => {
        if (isGizmoObject(obj) || isGridMesh(obj) || obj.userData?.isBackdrop) {
          restore.push({ obj, visible: obj.visible });
          obj.visible = false;
        }
      });
      gl.setRenderTarget(sourceTarget);
      gl.setClearColor(0x000000, 1);
      gl.clear(true, true, true);
      gl.render(scene, shotCam);
      restoreAll();

      // Measure the frame's actual depth band (min/max geometry viewZ) from a
      // packed-depth pass, then normalize the display map over it.
      const packed = runQuadPass(packDepthMaterial);
      let minZ = Infinity;
      let maxZ = 0;
      for (let i = 0; i < packed.length; i += 4) {
        const v = (packed[i] + packed[i + 1] / 255) / 255; // viewZ / cameraFar
        if (v >= 0.999) continue; // background
        const viewZ = v * CAM_FAR;
        if (viewZ < minZ) minZ = viewZ;
        if (viewZ > maxZ) maxZ = viewZ;
      }
      if (minZ < maxZ) {
        depthViewMaterial.uniforms.uRangeNear.value = minZ;
        depthViewMaterial.uniforms.uRangeFar.value = maxZ + (maxZ - minZ) * 0.02 + 1e-3;
      } else {
        // Empty frame — no geometry; the map is legitimately all background.
        depthViewMaterial.uniforms.uRangeNear.value = CAM_NEAR;
        depthViewMaterial.uniforms.uRangeFar.value = CAM_FAR;
      }

      const depthPixels = runQuadPass(depthViewMaterial);

      let normalPixels = null;
      let segPixels = null;
      if (captureMode === 'all') {
        normalPixels = runQuadPass(normalViewMaterial);
        segPixels = runMapPass((mesh) => {
          const root = segmentRoot(mesh, scene);
          let mat = segMaterials.get(root.uuid);
          if (!mat) {
            mat = new THREE.MeshBasicMaterial({
              color: segmentColor(root.uuid),
              side: THREE.DoubleSide,
            });
            segMaterials.set(root.uuid, mat);
          }
          return mat;
        });
      }

      scene.background = prevBackground;

      // ── Color (beauty) pass ──────────────────────────────────────────────
      // What the shot camera actually sees: backdrop + assets with their real
      // materials and background — the img2img init frame. Gizmos/grid stay out.
      scene.traverse((obj) => {
        if (isGizmoObject(obj) || isGridMesh(obj)) {
          restore.push({ obj, visible: obj.visible });
          obj.visible = false;
        }
      });

      gl.setRenderTarget(colorTarget);
      gl.clear(true, true, true);
      gl.render(scene, shotCam);
      const colorPixels = readTargetPixels(gl, colorTarget, width, height);
      restoreAll();

      // ── Clean plate pass (backdrop/environment only) ─────────────────────
      // Same shot camera and real materials as the beauty frame, but placed
      // assets + blockout hidden — a background plate for compositing/inpainting.
      // Only in 'all' mode (mirrors normal/seg). Reuses colorTarget (its beauty
      // pixels were already read above).
      let cleanPixels = null;
      if (captureMode === 'all') {
        scene.traverse((obj) => {
          if (isGizmoObject(obj) || isGridMesh(obj) || isStagingObject(obj)) {
            restore.push({ obj, visible: obj.visible });
            obj.visible = false;
          }
        });
        gl.setRenderTarget(colorTarget);
        gl.clear(true, true, true);
        gl.render(scene, shotCam);
        cleanPixels = readTargetPixels(gl, colorTarget, width, height);
        restoreAll();
      }
      gl.setRenderTarget(null);

      // ── Encode + upload (async; GPU state already restored) ──────────────
      const [depthBlob, colorBlob, normalBlob, segBlob, cleanBlob] = await Promise.all([
        pixelsToBlob(depthPixels, width, height),
        pixelsToBlob(colorPixels, width, height),
        normalPixels ? pixelsToBlob(normalPixels, width, height) : null,
        segPixels ? pixelsToBlob(segPixels, width, height) : null,
        cleanPixels ? pixelsToBlob(cleanPixels, width, height) : null,
      ]);

      await api.createCapture(sceneId, {
        depthMap: depthBlob,
        colorMap: colorBlob,
        normalMap: normalBlob,
        segMap: segBlob,
        cleanMap: cleanBlob,
        camera: piloting
          ? { ...shotCamera, position: camPosition, target: camTarget }
          : shotCamera,
        width,
        height,
      });
      queryClient.invalidateQueries({ queryKey: ['captures', sceneId] });
    } catch (e) {
      console.error('Capture failed', e);
    } finally {
      restoreAll();
      scene.background = prevBackground;
      gl.setRenderTarget(null);
      // Unbind the per-capture depth texture from the persistent quad materials.
      depthViewMaterial.uniforms.tDepth.value = null;
      normalViewMaterial.uniforms.tDepth.value = null;
      packDepthMaterial.uniforms.tDepth.value = null;
      mapTarget.dispose();
      colorTarget.dispose();
      sourceTarget.dispose();
      depthTexture.dispose();
      segMaterials.forEach((m) => m.dispose());
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
