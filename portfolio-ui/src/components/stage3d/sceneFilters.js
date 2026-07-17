// Predicates for excluding non-scene objects (editor chrome) from shot-camera
// renders — used by the capture passes and the pilot through-the-lens view.

export function isGizmoObject(obj) {
  return obj.userData?.hideInShot || obj.isTransformControlsRoot;
}

export function isGridMesh(obj) {
  // drei's infinite Grid — its shader material can't be swapped safely.
  return obj.isMesh && obj.material && 'worldCamProjPosition' in obj.material;
}

// Hide editor chrome (and optionally more) for a render; returns a restore fn.
export function hideForShot(scene, extraPredicate = null) {
  const hidden = [];
  scene.traverse((obj) => {
    const hide = isGizmoObject(obj) || isGridMesh(obj) || (extraPredicate && extraPredicate(obj));
    if (hide && obj.visible) {
      obj.visible = false;
      hidden.push(obj);
    }
  });
  return () => hidden.forEach((o) => { o.visible = true; });
}
