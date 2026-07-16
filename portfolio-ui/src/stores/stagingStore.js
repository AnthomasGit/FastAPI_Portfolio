import { create } from 'zustand';

export const useStagingStore = create((set, get) => ({
  placements: [],
  blockout: [],
  camera: null,
  backdropReferenceId: null,
  selection: null,
  transformMode: 'translate',
  dirty: false,
  isCapturing: false,
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
  setBackdropReferenceId: (id) => set((state) => ({
    backdropReferenceId: id, dirty: true, editVersion: state.editVersion + 1,
  })),
  setSelection: (id) => set({ selection: id }),
  setTransformMode: (mode) => set({ transformMode: mode }),
  setDirty: (v) => set({ dirty: v }),
  setIsCapturing: (v) => set({ isCapturing: v }),

  hydrationVersion: 0,
  hydrateFromServer: (data) => set((state) => ({
    placements: data.placements || [],
    blockout: data.blockout || [],
    camera: data.camera || null,
    backdropReferenceId: data.backdrop_reference_id || null,
    dirty: false,
    selection: null,
    hydrationVersion: state.hydrationVersion + 1,
  })),

  getUpdatePayload: () => {
    const { placements, blockout, camera, backdropReferenceId } = get();
    const payload = {};
    if (placements) payload.placements = placements;
    if (blockout) payload.blockout = blockout;
    if (camera) payload.camera = camera;
    payload.backdrop_reference_id = backdropReferenceId || null;
    return payload;
  },
}));
