// Milestones: one-time acknowledgements of finished *output*.
//
// Deliberately narrow. Research on gamifying professional creative tools is
// consistent that XP, levels, daily streaks and leaderboards backfire — they
// reward showing up rather than shipping, and read as patronising to people
// doing the work for a living. What survives is recognising a real artefact
// the first time it exists. So: no points, no streaks, no scores, and each
// milestone fires exactly once, ever.
//
// Flip MILESTONES_ENABLED to false to remove the whole layer.

export const MILESTONES_ENABLED = true;

const STORAGE_KEY = 'storyboard-pro:milestones';

function seen() {
  try {
    return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'));
  } catch {
    return new Set();
  }
}

function remember(id) {
  try {
    const all = seen();
    all.add(id);
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...all]));
  } catch {
    /* private mode / storage disabled — just don't celebrate twice this session */
  }
}

/**
 * Return the milestone to show for this event, or null. Marks it seen.
 * @param {{ firstClipEver?: boolean, sceneComplete?: {number, total} }} ctx
 */
export function claimMilestone(ctx) {
  if (!MILESTONES_ENABLED) return null;
  const already = seen();

  if (ctx.firstClipEver && !already.has('first-clip')) {
    remember('first-clip');
    return {
      id: 'first-clip',
      title: 'First clip generated',
      body: 'Your storyboard just became moving footage.',
    };
  }

  if (ctx.sceneComplete) {
    const id = `scene-complete:${ctx.sceneComplete.sceneId}`;
    if (!already.has(id)) {
      remember(id);
      return {
        id,
        title: `Scene ${ctx.sceneComplete.number} complete`,
        body: `All ${ctx.sceneComplete.total} shots have a clip.`,
      };
    }
  }

  return null;
}
