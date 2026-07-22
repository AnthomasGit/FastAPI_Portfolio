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

// ── Undo/redo ────────────────────────────────────────────────────────────────
// History captures the whole staging *document* per step. The store always
// replaces placements/blockout/camera/backdrop* immutably, so a captured
// reference is a valid, frozen snapshot — no deep clone needed.
const HISTORY_LIMIT = 50;
const COALESCE_MS = 400; // rapid same-tag edits (e.g. WASD nudges) collapse to one step

const PIP_SCALES = [1, 1.5, 2];

function snapshot(state) {
  return {
    placements: state.placements,
    blockout: state.blockout,
    camera: state.camera,
    backdropReferenceId: state.backdropReferenceId,
    backdropTransform: state.backdropTransform,
  };
}

// History-field updates to merge into a mutating setter's result. Called with
// the PRE-edit state, so the pushed snapshot is the state to return to. Same-tag
// edits within COALESCE_MS reuse the existing entry instead of adding a new one.
function recordHistory(state, tag) {
  const now = Date.now();
  if (tag === state._lastTag && now - state._lastPushAt < COALESCE_MS) {
    return { future: [], _lastPushAt: now };
  }
  return {
    past: [...state.past, snapshot(state)].slice(-HISTORY_LIMIT),
    future: [],
    _lastTag: tag,
    _lastPushAt: now,
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
  pilotMode: false,
  fastMode: false,
  captureMode: 'all', // 'all' (depth+normal+seg) | 'depth'
  pipScale: 1,
  editVersion: 0,

  // Undo/redo history
  past: [],
  future: [],
  _lastTag: null,
  _lastPushAt: 0,

  setPlacements: (placements) => set((state) => ({
    placements, dirty: true, editVersion: state.editVersion + 1,
    ...recordHistory(state, 'placements'),
  })),
  setBlockout: (blockout) => set((state) => ({
    blockout, dirty: true, editVersion: state.editVersion + 1,
    ...recordHistory(state, 'blockout'),
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
      ...recordHistory(state, 'add'),
    };
  }),
  removeBlockout: (id) => set((state) => ({
    blockout: state.blockout.filter((b) => b.id !== id),
    selection: state.selection === id ? null : state.selection,
    dirty: true,
    editVersion: state.editVersion + 1,
    ...recordHistory(state, 'remove'),
  })),
  removePlacement: (id) => set((state) => ({
    placements: state.placements.filter((p) => p.id !== id),
    selection: state.selection === id ? null : state.selection,
    dirty: true,
    editVersion: state.editVersion + 1,
    ...recordHistory(state, 'remove'),
  })),
  setCamera: (camera) => set((state) => ({
    camera, dirty: true, editVersion: state.editVersion + 1,
    ...recordHistory(state, 'camera'),
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
    return {
      camera: next, dirty: true, editVersion: state.editVersion + 1,
      ...recordHistory(state, 'camera'),
    };
  }),
  // Ephemeral live navigation-camera pose (not persisted, does not mark dirty).
  setNavPose: (navPose) => set({ navPose }),
  setBackdropReferenceId: (id) => set((state) => ({
    backdropReferenceId: id, dirty: true, editVersion: state.editVersion + 1,
    ...recordHistory(state, 'backdrop-ref'),
  })),
  setBackdropTransform: (transform) => set((state) => ({
    backdropTransform: transform, dirty: true, editVersion: state.editVersion + 1,
    ...recordHistory(state, 'backdrop'),
  })),
  setSelection: (id) => set({ selection: id }),
  setTransformMode: (mode) => set({ transformMode: mode }),
  setDirty: (v) => set({ dirty: v }),
  setIsCapturing: (v) => set({ isCapturing: v }),
  // Registered by CaptureRenderer (inside the Canvas) so out-of-Canvas UI can
  // trigger a capture. Stored via a wrapper so zustand doesn't treat the fn as
  // a state updater.
  setCaptureFn: (fn) => set({ captureFn: fn }),
  setPilotMode: (v) => set({ pilotMode: v }),
  toggleFastMode: () => set((state) => ({ fastMode: !state.fastMode })),
  setCaptureMode: (mode) => set({ captureMode: mode }),
  // Cycle the shot-preview PiP through its size presets (ephemeral, not saved).
  cyclePipScale: () => set((state) => {
    const i = PIP_SCALES.indexOf(state.pipScale);
    return { pipScale: PIP_SCALES[(i + 1) % PIP_SCALES.length] };
  }),

  // Nudge the selected placement/blockout/backdrop by a world-space offset.
  // Called at frame rate while movement keys are held (same scale/pattern as
  // the original drag-time store writes). Per-object 'move' tag coalesces a
  // nudge burst into one undo step.
  moveSelected: (offset) => set((state) => {
    const sel = state.selection;
    if (!sel) return {};
    const [dx, dy, dz] = offset;
    const bump = {
      dirty: true,
      editVersion: state.editVersion + 1,
      ...recordHistory(state, `move:${sel}`),
    };

    if (sel === 'backdrop') {
      const t = state.backdropTransform || {
        pos: [0, 1.5, -5], rot: [0, 0, 0], scale: [4, 3, 1],
      };
      const pos = t.pos || [0, 1.5, -5];
      return {
        backdropTransform: { ...t, pos: [pos[0] + dx, pos[1] + dy, pos[2] + dz] },
        ...bump,
      };
    }
    if (state.placements.some((p) => p.id === sel)) {
      return {
        placements: state.placements.map((p) => {
          if (p.id !== sel) return p;
          const pos = p.transform?.pos || [0, 0, 0];
          return {
            ...p,
            transform: { ...p.transform, pos: [pos[0] + dx, pos[1] + dy, pos[2] + dz] },
          };
        }),
        ...bump,
      };
    }
    if (state.blockout.some((b) => b.id === sel)) {
      return {
        blockout: state.blockout.map((b) => {
          if (b.id !== sel) return b;
          const pos = b.transform?.pos || [0, 0, 0];
          return {
            ...b,
            transform: { ...b.transform, pos: [pos[0] + dx, pos[1] + dy, pos[2] + dz] },
          };
        }),
        ...bump,
      };
    }
    return {};
  }),

  undo: () => set((state) => {
    if (!state.past.length) return {};
    const prev = state.past[state.past.length - 1];
    return {
      ...prev,
      past: state.past.slice(0, -1),
      future: [snapshot(state), ...state.future].slice(0, HISTORY_LIMIT),
      dirty: true,
      editVersion: state.editVersion + 1,
      selection: null,
      _lastTag: null,
      _lastPushAt: 0,
    };
  }),
  redo: () => set((state) => {
    if (!state.future.length) return {};
    const next = state.future[0];
    return {
      ...next,
      future: state.future.slice(1),
      past: [...state.past, snapshot(state)].slice(-HISTORY_LIMIT),
      dirty: true,
      editVersion: state.editVersion + 1,
      selection: null,
      _lastTag: null,
      _lastPushAt: 0,
    };
  }),

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
    pilotMode: false,
    hydrationVersion: state.hydrationVersion + 1,
    // A fresh scene load starts with an empty history.
    past: [],
    future: [],
    _lastTag: null,
    _lastPushAt: 0,
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
