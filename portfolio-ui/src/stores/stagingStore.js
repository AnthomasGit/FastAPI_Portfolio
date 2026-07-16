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

  setPlacements: (placements) => set({ placements, dirty: true }),
  setBlockout: (blockout) => set({ blockout, dirty: true }),
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
    };
  }),
  removeBlockout: (id) => set((state) => ({
    blockout: state.blockout.filter((b) => b.id !== id),
    selection: state.selection === id ? null : state.selection,
    dirty: true,
  })),
  removePlacement: (id) => set((state) => ({
    placements: state.placements.filter((p) => p.id !== id),
    selection: state.selection === id ? null : state.selection,
    dirty: true,
  })),
  setCamera: (camera) => set({ camera, dirty: true }),
  setBackdropReferenceId: (id) => set({ backdropReferenceId: id, dirty: true }),
  setSelection: (id) => set({ selection: id }),
  setTransformMode: (mode) => set({ transformMode: mode }),
  setDirty: (v) => set({ dirty: v }),
  setIsCapturing: (v) => set({ isCapturing: v }),

  hydrateFromServer: (data) => set({
    placements: data.placements || [],
    blockout: data.blockout || [],
    camera: data.camera || null,
    backdropReferenceId: data.backdrop_reference_id || null,
    dirty: false,
    selection: null,
  }),

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
