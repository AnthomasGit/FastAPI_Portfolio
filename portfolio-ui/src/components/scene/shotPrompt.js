// Compose a shot's coverage metadata into an LTX motion prompt. This is why
// the shot list carries size/angle/movement/audio — they steer the clip, not
// just document intent. Editable before submit.
const SIZE_LABEL = {
  WS: 'wide shot', MS: 'medium shot', MCU: 'medium close-up', CU: 'close-up',
  ECU: 'extreme close-up', POV: 'point-of-view shot', OTS: 'over-the-shoulder shot',
  'Two-Shot': 'two-shot',
};

const MOVEMENT_CLAUSE = {
  Static: 'The camera holds steady',
  Pan: 'The camera pans smoothly',
  Tilt: 'The camera tilts',
  Tracking: 'The camera tracks the subject',
  Dolly: 'The camera dollies in',
  Handheld: 'Handheld camera with subtle movement',
  Crane: 'A sweeping crane move',
  Zoom: 'The camera slowly zooms',
};

export function shotToMotionPrompt(shot) {
  if (!shot) return '';
  const parts = [];
  const size = SIZE_LABEL[shot.shot_size] || (shot.shot_size ? shot.shot_size.toLowerCase() : null);
  const framing = [size, shot.angle && `${shot.angle.toLowerCase()} angle`]
    .filter(Boolean)
    .join(', ');
  if (framing) parts.push(`Style: cinematic ${framing}.`);
  if (shot.description) parts.push(shot.description.trim().replace(/\.$/, '') + '.');
  const move = MOVEMENT_CLAUSE[shot.movement];
  if (move) parts.push(move + '.');
  if (shot.audio_notes) parts.push(`Audio: ${shot.audio_notes.trim().replace(/\.$/, '')}.`);
  return parts.join(' ') || 'Gentle ambient motion, the camera holds steady.';
}
