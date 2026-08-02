// Derived shot state, shared by the shot-list badge and the Clip Studio
// checklist so the two can never disagree about whether a shot is ready.
//
// Nothing here is stored: every value is computed from the shot's own fields
// and its clip attempts. A shot's clips arrive from two places depending on
// the workflow that made them — reference-driven ones attach to the shot
// (`shot.videos`), still-driven ones hang off the chosen still
// (`shot.still.videos`) — so always read them through `allClips`.

export function allClips(shot) {
  if (!shot) return [];
  return [...(shot.videos || []), ...(shot.still?.videos || [])].sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at)
  );
}

export function clipState(shot) {
  const clips = allClips(shot);
  if (clips.some((c) => c.status === 'queued' || c.status === 'processing')) {
    return 'generating';
  }
  if (clips.some((c) => c.status === 'completed')) return 'done';
  if (clips.length && clips.every((c) => c.status === 'failed')) return 'failed';
  return 'none';
}

// What a shot needs before a clip is worth generating. `description` is the
// only genuinely load-bearing field — the rest sharpen the prompt — so the
// others are advisory and don't gate the button.
export function shotRequirements(shot) {
  return [
    { key: 'description', label: 'Action described', met: Boolean(shot?.description?.trim()), required: true },
    { key: 'size', label: 'Shot size set', met: Boolean(shot?.shot_size), required: false },
    { key: 'angle', label: 'Angle set', met: Boolean(shot?.angle), required: false },
    { key: 'movement', label: 'Camera movement set', met: Boolean(shot?.movement), required: false },
  ];
}

/**
 * One label + palette for a shot, for the shot-list badge.
 * draft -> not enough to generate | ready -> can generate | generating | done
 */
export function shotReadiness(shot) {
  const reqs = shotRequirements(shot);
  const met = reqs.filter((r) => r.met).length;
  const blocking = reqs.filter((r) => r.required && !r.met);
  const state = clipState(shot);

  if (state === 'generating') {
    return { key: 'generating', label: 'Generating', met, total: reqs.length, blocking,
      cls: 'bg-sky-500/15 text-sky-300' };
  }
  if (state === 'done') {
    return { key: 'done', label: 'Has clip', met, total: reqs.length, blocking,
      cls: 'bg-fuchsia-500/15 text-fuchsia-300' };
  }
  if (state === 'failed') {
    return { key: 'failed', label: 'Failed', met, total: reqs.length, blocking,
      cls: 'bg-red-500/15 text-red-300' };
  }
  if (blocking.length) {
    return { key: 'draft', label: 'Draft', met, total: reqs.length, blocking,
      cls: 'bg-white/5 text-slate-400' };
  }
  return { key: 'ready', label: 'Ready', met, total: reqs.length, blocking,
    cls: 'bg-emerald-500/15 text-emerald-300' };
}

/** Scene-level progress for the shot-list header. */
export function sceneClipProgress(shots = []) {
  const withClips = shots.filter((s) => clipState(s) === 'done').length;
  return { done: withClips, total: shots.length,
    pct: shots.length ? Math.round((withClips / shots.length) * 100) : 0 };
}
