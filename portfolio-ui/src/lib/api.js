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
  getScene: (id) => fetchJSON(`/scenes/${id}`),
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

  listCharacters: (projectId) => fetchJSON(`/projects/${projectId}/characters`),
  listLocations: (projectId) => fetchJSON(`/projects/${projectId}/locations`),
  listProps: (projectId) => fetchJSON(`/projects/${projectId}/props`),

  // Scene ↔ asset links (entityType is plural: characters | locations | props)
  linkSceneEntity: (sceneId, entityType, entityId, referenceId = null) =>
    fetchJSON(`/scenes/${sceneId}/links/${entityType}/${entityId}`, {
      method: 'POST',
      body: JSON.stringify({ reference_id: referenceId }),
    }),
  setSceneEntityReference: (sceneId, entityType, entityId, referenceId) =>
    fetchJSON(`/scenes/${sceneId}/links/${entityType}/${entityId}`, {
      method: 'PUT',
      body: JSON.stringify({ reference_id: referenceId }),
    }),
  unlinkSceneEntity: (sceneId, entityType, entityId) =>
    fetchJSON(`/scenes/${sceneId}/links/${entityType}/${entityId}`, { method: 'DELETE' }),

  generateScene: (sceneId) => fetchJSON(`/generate/scene/${sceneId}`, { method: 'POST' }),
  generateProject: (projectId) => fetchJSON(`/generate/project/${projectId}`, { method: 'POST' }),

  // Batches (Phase 1). `spec`: { project_id, scope, kind, target_ids, workflow,
  // variants, seed_policy, priority, run_after, params, name }.
  createBatch: (spec) => fetchJSON('/batches', { method: 'POST', body: JSON.stringify(spec) }),
  getGenerationStatus: (genId) => fetchJSON(`/generate/status/${genId}`),
  generateControlled: (captureId, { promptOverride, params } = {}) =>
    fetchJSON('/generate/controlled', {
      method: 'POST',
      body: JSON.stringify({
        capture_id: captureId,
        prompt_override: promptOverride ?? null,
        params: params ?? null,
      }),
    }),
  getGeneratedImageUrl: (genId) => `${API_BASE}/generate/image/${genId}`,

  // Video: takes a *completed* GeneratedImage (the beauty-pass still), not a capture.
  generateVideo: (imageId, { motionPrompt, params } = {}) =>
    fetchJSON('/generate/video', {
      method: 'POST',
      body: JSON.stringify({
        image_id: imageId,
        motion_prompt: motionPrompt ?? null,
        params: params ?? null,
      }),
    }),

  // The clip-workflow registry (capabilities drive the Clip Studio picker).
  listVideoWorkflows: () => fetchJSON('/video-workflows'),

  // Clip generation with an explicit workflow. Reference-driven workflows need
  // no still, so image_id is optional and the clip hangs off the shot instead.
  generateClip: ({
    workflow, shotId, imageId, referenceIds, backgroundReferenceId,
    firstFrameReferenceId, lastFrameReferenceId,
    drivingVideoId, refVideoIds, refAudioIds, motionPrompt, globalPrompt, localPrompts, params,
  } = {}) =>
    fetchJSON('/generate/video', {
      method: 'POST',
      body: JSON.stringify({
        workflow: workflow ?? null,
        shot_id: shotId ?? null,
        image_id: imageId ?? null,
        reference_ids: referenceIds ?? [],
        background_reference_id: backgroundReferenceId ?? null,
        first_frame_reference_id: firstFrameReferenceId ?? null,
        last_frame_reference_id: lastFrameReferenceId ?? null,
        driving_video_id: drivingVideoId ?? null,
        ref_video_ids: refVideoIds ?? [],
        ref_audio_ids: refAudioIds ?? [],
        motion_prompt: motionPrompt ?? null,
        global_prompt: globalPrompt ?? null,
        local_prompts: localPrompts ?? null,
        params: params ?? null,
      }),
    }),
  getVideoStatus: (videoId) => fetchJSON(`/generate/video/status/${videoId}`),
  getVideoFileUrl: (videoId) => `${API_BASE}/generate/video/file/${videoId}`,

  // Driving-video library (SCAIL-2's motion source). Reusable across projects
  // by design, so listDrivingVideos takes projectId as an optional filter,
  // not a hard scope.
  uploadDrivingVideo: async (file, { projectId, label } = {}) => {
    const formData = new FormData();
    formData.append('file', file);
    const qs = new URLSearchParams();
    if (projectId) qs.set('project_id', projectId);
    if (label) qs.set('label', label);
    const q = qs.toString() ? `?${qs}` : '';
    const res = await fetch(`${API_BASE}/driving-videos${q}`, { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Upload failed');
    }
    return res.json();
  },
  listDrivingVideos: (projectId) =>
    fetchJSON(projectId ? `/driving-videos?project_id=${projectId}` : '/driving-videos'),
  deleteDrivingVideo: (id) => fetchJSON(`/driving-videos/${id}`, { method: 'DELETE' }),
  getDrivingVideoUrl: (v) => `${API_BASE}/uploads/file/${v.video_url}`,

  // Reference-audio library (MiniMax H3 R2V's standalone audio slots). Same
  // reusable cross-project shape as the driving-video library above.
  uploadReferenceAudio: async (file, { projectId, label } = {}) => {
    const formData = new FormData();
    formData.append('file', file);
    const qs = new URLSearchParams();
    if (projectId) qs.set('project_id', projectId);
    if (label) qs.set('label', label);
    const q = qs.toString() ? `?${qs}` : '';
    const res = await fetch(`${API_BASE}/reference-audios${q}`, { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Upload failed');
    }
    return res.json();
  },
  listReferenceAudios: (projectId) =>
    fetchJSON(projectId ? `/reference-audios?project_id=${projectId}` : '/reference-audios'),
  deleteReferenceAudio: (id) => fetchJSON(`/reference-audios/${id}`, { method: 'DELETE' }),
  getReferenceAudioUrl: (a) => `${API_BASE}/uploads/file/${a.audio_url}`,

  // Master shot list (per scene).
  listShots: (sceneId) => fetchJSON(`/scenes/${sceneId}/shots`),
  createShot: (sceneId, data) => fetchJSON(`/scenes/${sceneId}/shots`, { method: 'POST', body: JSON.stringify(data) }),
  updateShot: (shotId, data) => fetchJSON(`/shots/${shotId}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteShot: (shotId) => fetchJSON(`/shots/${shotId}`, { method: 'DELETE' }),
  reorderShots: (sceneId, shotIds) => fetchJSON(`/scenes/${sceneId}/shots/reorder`, { method: 'PUT', body: JSON.stringify({ shot_ids: shotIds }) }),
  generateShotList: (sceneId) => fetchJSON(`/scenes/${sceneId}/shots/generate`, { method: 'POST' }),

  // A per-scene entity link's thumbnail. Mirrors getReferenceFileUrl's
  // precedence: check is_processed FIRST. A background-removed reference's
  // reference_url is already the processed_url (input-dir-servable), even
  // when asset_image_id is still set — only an unprocessed asset-image
  // reference needs the output-dir asset-images route.
  getLinkThumbUrl: (link) =>
    !link?.reference_url && !link?.asset_image_id
      ? null
      : link.asset_image_id && !link.is_processed
        ? `${API_BASE}/asset-images/${link.asset_image_id}/file`
        : `${API_BASE}/uploads/file/${link.reference_url}`,

  getProjectGraph: (projectId) => fetchJSON(`/projects/${projectId}/graph`),

  upload: (file) => uploadFile(file),

  listReferences: (entityType, entityId) => fetchJSON(`/${entityType}/${entityId}/references`),

  listProjectReferences: (projectId, entityType) => fetchJSON(`/projects/${projectId}/references?entity_type=${entityType}`),

  createReference: (entityType, entityId, data) => fetchJSON(`/${entityType}/${entityId}/references`, { method: 'POST', body: JSON.stringify(data) }),

  updateReference: (id, data) => fetchJSON(`/references/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteReference: (id) => fetchJSON(`/references/${id}`, { method: 'DELETE' }),

  removeBackground: (id) => fetchJSON(`/references/${id}/remove-background`, { method: 'POST' }),

  restoreBackground: (id) => fetchJSON(`/references/${id}/remove-background`, { method: 'DELETE' }),

  generateAssetImage: (data) => fetchJSON('/asset-images/generate', { method: 'POST', body: JSON.stringify(data) }),

  listAssetImages: (params = {}) => {
    const qs = new URLSearchParams();
    if (params.entity_type) qs.set('entity_type', params.entity_type);
    if (params.project_id) qs.set('project_id', params.project_id);
    const q = qs.toString();
    return fetchJSON(`/asset-images${q ? `?${q}` : ''}`);
  },

  getAssetImage: (id) => fetchJSON(`/asset-images/${id}`),

  getAssetImageFile: (id) => `${API_BASE}/asset-images/${id}/file`,
  getReferenceFileUrl: (ref, { processed = true } = {}) =>
    (processed && ref.processed_url)
      ? `${API_BASE}/uploads/file/${ref.processed_url}`
      : ref.asset_image_id
        ? `${API_BASE}/asset-images/${ref.asset_image_id}/file`
        : `${API_BASE}/uploads/file/${ref.url}`,

  assignAssetImage: (entityType, entityId, assetImageId) =>
    fetchJSON(`/${entityType}/${entityId}/assign-asset`, { method: 'POST', body: JSON.stringify({ asset_image_id: assetImageId }) }),

  generateAsset3D: (data) => fetchJSON('/assets3d/generate', { method: 'POST', body: JSON.stringify(data) }),
  getAsset3D: (id) => fetchJSON(`/assets3d/${id}`),
  listAssets3D: (projectId) => fetchJSON(`/projects/${projectId}/assets3d`),
  retryAsset3D: (id) => fetchJSON(`/assets3d/${id}/retry`, { method: 'POST' }),
  getAsset3DFile: (id, rigged = false) => `${API_BASE}/assets3d/${id}/mesh${rigged ? '?rigged=true' : ''}`,
  deleteAsset3D: (id) => fetchJSON(`/assets3d/${id}`, { method: 'DELETE' }),

  getStaging: (sceneId) => fetchJSON(`/scenes/${sceneId}/staging`),
  putStaging: (sceneId, data) => fetchJSON(`/scenes/${sceneId}/staging`, { method: 'PUT', body: JSON.stringify(data) }),

  createStagingSave: (sceneId, name) => fetchJSON(`/scenes/${sceneId}/staging/saves`, { method: 'POST', body: JSON.stringify({ name }) }),
  listStagingSaves: (sceneId) => fetchJSON(`/scenes/${sceneId}/staging/saves`),
  restoreStagingSave: (saveId) => fetchJSON(`/staging-saves/${saveId}/restore`, { method: 'POST' }),
  updateStagingSave: (saveId) => fetchJSON(`/staging-saves/${saveId}`, { method: 'PUT' }),
  deleteStagingSave: (saveId) => fetchJSON(`/staging-saves/${saveId}`, { method: 'DELETE' }),

  createCapture: async (sceneId, { depthMap, edgeMap, colorMap, normalMap, segMap, cleanMap, camera, width, height }) => {
    const formData = new FormData();
    formData.append('depth_map', depthMap, 'depth.png');
    if (edgeMap) formData.append('edge_map', edgeMap, 'edge.png');
    if (colorMap) formData.append('color_map', colorMap, 'color.png');
    if (normalMap) formData.append('normal_map', normalMap, 'normal.png');
    if (segMap) formData.append('seg_map', segMap, 'seg.png');
    if (cleanMap) formData.append('clean_map', cleanMap, 'clean.png');
    formData.append('camera', JSON.stringify(camera));
    formData.append('width', String(width));
    formData.append('height', String(height));
    const res = await fetch(`${API_BASE}/scenes/${sceneId}/staging/captures`, { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Capture failed');
    }
    return res.json();
  },

  listCaptures: (sceneId) => fetchJSON(`/scenes/${sceneId}/staging/captures`),

  getCaptureDepthUrl: (captureId) => `${API_BASE}/captures/${captureId}/depth`,
  getCaptureColorUrl: (captureId) => `${API_BASE}/captures/${captureId}/color`,
  getCaptureNormalUrl: (captureId) => `${API_BASE}/captures/${captureId}/normal`,
  getCaptureSegUrl: (captureId) => `${API_BASE}/captures/${captureId}/seg`,
  getCaptureCleanUrl: (captureId) => `${API_BASE}/captures/${captureId}/clean`,

  deleteCapture: (captureId) => fetchJSON(`/captures/${captureId}`, { method: 'DELETE' }),
};
