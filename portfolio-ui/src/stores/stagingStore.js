import { create } from 'zustand';
import {
  getFormat,
  focalLengthToFov,
  DEFAULT_FORMAT,
  DEFAULT_FOCAL_LENGTH,
} from '@/components/stage3d/cameraFormats';

// Ensure a shot camera always carries focal_length/format/fov, defaulting older
// or empty stagings (whose camera was just an orbit pose) into a valid shot.
function normalizeShotCamera(camera) {
  if (!camera) return null;
  const focal = camera.focal_length || DEFAULT_FOCAL_LENGTH;
  const format = getFormat(camera.format || DEFAULT_FORMAT);
  return {
    ...camera,
    focal_length: focal,
    format: format.id,
    fov: focalLengthToFov(focal, format.aspect),
  };
}

export const useStagingStore = create((set, get) => ({
  placements: [],
  blockout: [],
  camera: null,
  navPose: null,
  backdropReferenceId: null,
  backdropTransform: null,
  selection: null,
  transformMode: 'translate',
  dirty: false,
  isCapturing: false,
  captureFn: null,
  editVersion: 0,

  setPlacements: (placements) => set((state) => ({
    placements, dirty: true, editVersion: state.editVersion + 1,
  })),
  setBlockout: (blockout) => set((state) => ({
    blockout, dirty: true, editVersion: state.editVersion + 1,
  })),
  addPlacement: (asset3dId) => set((state) => {
    const id = `placement-${Date.now()}`;
    return {
      placements: [...state.placements, {
        id,
        asset3d_id: asset3dId,
        transform: { pos: [0, 0, 0], rot: [0, 0, 0], scale: [1, 1, 1] },
      }],
      selection: id,
      dirty: true,
      editVersion: state.editVersion + 1,
    };
  }),
  removeBlockout: (id) => set((state) => ({
    blockout: state.blockout.filter((b) => b.id !== id),
    selection: state.selection === id ? null : state.selection,
    dirty: true,
    editVersion: state.editVersion + 1,
  })),
  removePlacement: (id) => set((state) => ({
    placements: state.placements.filter((p) => p.id !== id),
    selection: state.selection === id ? null : state.selection,
    dirty: true,
    editVersion: state.editVersion + 1,
  })),
  setCamera: (camera) => set((state) => ({
    camera, dirty: true, editVersion: state.editVersion + 1,
  })),
  // Merge a partial update into the shot camera, recomputing fov whenever the
  // focal length or format changes so the three consumers (PiP, gizmo, capture)
  // stay in sync from a single stored source.
  updateShotCamera: (partial) => set((state) => {
    const prev = state.camera || {};
    const next = { ...prev, ...partial };
    const focal = next.focal_length || DEFAULT_FOCAL_LENGTH;
    const format = getFormat(next.format || DEFAULT_FORMAT);
    next.focal_length = focal;
    next.format = format.id;
    next.fov = focalLengthToFov(focal, format.aspect);
    return { camera: next, dirty: true, editVersion: state.editVersion + 1 };
  }),
  // Ephemeral live navigation-camera pose (not persisted, does not mark dirty).
  setNavPose: (navPose) => set({ navPose }),
  setBackdropReferenceId: (id) => set((state) => ({
    backdropReferenceId: id, dirty: true, editVersion: state.editVersion + 1,
  })),
  setBackdropTransform: (transform) => set((state) => ({
    backdropTransform: transform, dirty: true, editVersion: state.editVersion + 1,
  })),
  setSelection: (id) => set({ selection: id }),
  setTransformMode: (mode) => set({ transformMode: mode }),
  setDirty: (v) => set({ dirty: v }),
  setIsCapturing: (v) => set({ isCapturing: v }),
  // Registered by CaptureRenderer (inside the Canvas) so out-of-Canvas UI can
  // trigger a capture. Stored via a wrapper so zustand doesn't treat the fn as
  // a state updater.
  setCaptureFn: (fn) => set({ captureFn: fn }),

  hydrationVersion: 0,
  hydrateFromServer: (data) => set((state) => ({
    placements: data.placements || [],
    blockout: data.blockout || [],
    camera: normalizeShotCamera(data.camera),
    navPose: null,
    backdropReferenceId: data.backdrop_reference_id || null,
    backdropTransform: data.backdrop_transform || null,
    dirty: false,
    selection: null,
    hydrationVersion: state.hydrationVersion + 1,
  })),

  getUpdatePayload: () => {
    const { placements, blockout, camera, backdropReferenceId, backdropTransform } = get();
    const payload = {};
    if (placements) payload.placements = placements;
    if (blockout) payload.blockout = blockout;
    if (camera) payload.camera = camera;
    payload.backdrop_reference_id = backdropReferenceId || null;
    if (backdropTransform) payload.backdrop_transform = backdropTransform;
    return payload;
  },
}));
