const API_BASE = '/api';

async function fetchJSON(url, options = {}) {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  if (res.status == 204) return null;
  return res.json();
}

async function uploadFile(file) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/uploads`, { method: 'POST', body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Upload failed');
  }
  return res.json();
}

export const api = {
  listProjects: () => fetchJSON('/projects'),
  getProject: (id) => fetchJSON(`/projects/${id}`),
  createProject: (data) => fetchJSON('/projects', { method: 'POST', body: JSON.stringify(data) }),
  updateProject: (id, data) => fetchJSON(`/projects/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteProject: (id) => fetchJSON(`/projects/${id}`, { method: 'DELETE' }),

  clarifyIdea: (idea) => fetchJSON('/ai/clarify', { method: 'POST', body: JSON.stringify({ idea }) }),
  generateStoryboard: (idea, answers) => fetchJSON('/ai/generate-storyboard', { method: 'POST', body: JSON.stringify({ idea, answers }) }),

  createScene: (projectId, data) => fetchJSON(`/projects/${projectId}/scenes`, { method: 'POST', body: JSON.stringify(data) }),
  updateScene: (id, data) => fetchJSON(`/scenes/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteScene: (id) => fetchJSON(`/scenes/${id}`, { method: 'DELETE' }),
  reorderScenes: (sceneIds) => fetchJSON('/scenes/reorder', { method: 'PUT', body: JSON.stringify({ scene_ids: sceneIds }) }),

  createCharacter: (projectId, data) => fetchJSON(`/projects/${projectId}/characters`, { method: 'POST', body: JSON.stringify(data) }),
  updateCharacter: (id, data) => fetchJSON(`/characters/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteCharacter: (id) => fetchJSON(`/characters/${id}`, { method: 'DELETE' }),

  createLocation: (projectId, data) => fetchJSON(`/projects/${projectId}/locations`, { method: 'POST', body: JSON.stringify(data) }),
  updateLocation: (id, data) => fetchJSON(`/locations/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteLocation: (id) => fetchJSON(`/locations/${id}`, { method: 'DELETE' }),

  createProp: (projectId, data) => fetchJSON(`/projects/${projectId}/props`, { method: 'POST', body: JSON.stringify(data) }),
  updateProp: (id, data) => fetchJSON(`/props/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteProp: (id) => fetchJSON(`/props/${id}`, { method: 'DELETE' }),

  generateScene: (sceneId) => fetchJSON(`/generate/scene/${sceneId}`, { method: 'POST' }),
  generateProject: (projectId) => fetchJSON(`/generate/project/${projectId}`, { method: 'POST' }),
  getGenerationStatus: (genId) => fetchJSON(`/generate/status/${genId}`),

  getProjectGraph: (projectId) => fetchJSON(`/projects/${projectId}/graph`),

  upload: (file) => uploadFile(file),

  listReferences: (entityType, entityId) => fetchJSON(`/${entityType}/${entityId}/references`),

  createReference: (entityType, entityId, data) => fetchJSON(`/${entityType}/${entityId}/references`, { method: 'POST', body: JSON.stringify(data) }),

  updateReference: (id, data) => fetchJSON(`/references/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteReference: (id) => fetchJSON(`/references/${id}`, { method: 'DELETE' }),

  removeBackground: (id) => fetchJSON(`/references/${id}/remove-background`, { method: 'POST' }),
};
