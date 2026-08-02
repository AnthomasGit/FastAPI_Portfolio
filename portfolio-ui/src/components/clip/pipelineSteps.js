// Build the stepper model for one shot. Split from PipelineStepper.jsx so that
// file exports components only (react-refresh requirement).
//
// Every state is derived, never stored: the stepper is a readout of what
// actually exists, so it can't drift from reality.

export function buildPipelineSteps({ scene, shot, hasCapture, clipState }) {
  const hasStill = Boolean(shot?.still);
  return [
    { key: 'story', label: 'Story', state: 'done' },
    { key: 'scenes', label: 'Scenes', state: scene ? 'done' : 'upcoming' },
    // Reaching this page means the shot exists.
    { key: 'shots', label: 'Shot list', state: 'done' },
    // Optional branches: absent reads as "skipped", not "incomplete".
    { key: 'stage', label: '3D staging', optional: true, state: hasCapture ? 'done' : 'skipped' },
    { key: 'still', label: 'Still', optional: true, state: hasStill ? 'done' : 'skipped' },
    { key: 'clip', label: 'Clip', state: clipState === 'done' ? 'done' : 'active' },
  ];
}
