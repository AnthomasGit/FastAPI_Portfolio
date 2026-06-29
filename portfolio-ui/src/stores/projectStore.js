import { create } from 'zustand';

export const useProjectStore = create((set) => ({
  currentProject: null,
  projects: [],
  loading: false,
  error: null,

  setProjects: (projects) => set({ projects }),
  setCurrentProject: (project) => set({ currentProject: project }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),

  updateScene: (sceneId, updates) => set((state) => {
    if (!state.currentProject) return state;
    return {
      currentProject: {
        ...state.currentProject,
        scenes: state.currentProject.scenes.map((s) =>
          s.id === sceneId ? { ...s, ...updates } : s
        ),
      },
    };
  }),
}));
