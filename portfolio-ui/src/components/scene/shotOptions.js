// Fixed vocabularies for shot metadata, matching the system prompt
// ai_service.generate_shot_list uses to draft shots — so AI-drafted values
// line up with these dropdown options. Each field cycles its own set of
// colors so values are visually distinct within a column.
const PALETTE = [
  { bg: 'bg-set/15', text: 'text-set', ring: 'focus:ring-set' },
  { bg: 'bg-cast/15', text: 'text-cast', ring: 'focus:ring-cast' },
  { bg: 'bg-lead-500/15', text: 'text-lead-400', ring: 'focus:ring-lead-500' },
  { bg: 'bg-clip/15', text: 'text-clip', ring: 'focus:ring-clip' },
  { bg: 'bg-prop/15', text: 'text-prop', ring: 'focus:ring-prop' },
  { bg: 'bg-stop/15', text: 'text-stop', ring: 'focus:ring-stop' },
  { bg: 'bg-ok/15', text: 'text-ok', ring: 'focus:ring-ok' },
  { bg: 'bg-fg/10', text: 'text-fg', ring: 'focus:ring-fg' },
];
const NEUTRAL = { bg: 'bg-bay-800', text: 'text-fg-muted', ring: 'focus:ring-lead-500' };

function buildField(options) {
  const colorOf = {};
  options.forEach((o, i) => { colorOf[o] = PALETTE[i % PALETTE.length]; });
  return { options, colorOf };
}

export const SHOT_SIZE = buildField(['WS', 'MS', 'MCU', 'CU', 'ECU', 'POV', 'OTS', 'Two-Shot']);
export const ANGLE = buildField(['High', 'Eye-Level', 'Low', 'Dutch', 'Overhead']);
export const MOVEMENT = buildField(['Static', 'Pan', 'Tilt', 'Tracking', 'Dolly', 'Handheld', 'Crane', 'Zoom']);
// Open-ended per the AI prompt ("e.g. Tripod, Gimbal...") — still a fixed
// dropdown per the user's choice, but an unrecognized value (hand-typed or
// AI-drafted outside this list) is preserved as its own selectable option
// rather than silently dropped (see BadgeSelectCell).
export const EQUIPMENT = buildField(['Tripod', 'Gimbal', 'Handheld', 'Dolly track', 'Crane']);

export function colorFor(fieldConfig, value) {
  return (value && fieldConfig.colorOf[value]) || NEUTRAL;
}
