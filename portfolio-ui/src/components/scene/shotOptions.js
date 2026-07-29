// Fixed vocabularies for shot metadata, matching the system prompt
// ai_service.generate_shot_list uses to draft shots — so AI-drafted values
// line up with these dropdown options. Each field cycles its own set of
// colors so values are visually distinct within a column.
const PALETTE = [
  { bg: 'bg-sky-500/15', text: 'text-sky-300', ring: 'focus:ring-sky-400' },
  { bg: 'bg-emerald-500/15', text: 'text-emerald-300', ring: 'focus:ring-emerald-400' },
  { bg: 'bg-amber-500/15', text: 'text-amber-300', ring: 'focus:ring-amber-400' },
  { bg: 'bg-fuchsia-500/15', text: 'text-fuchsia-300', ring: 'focus:ring-fuchsia-400' },
  { bg: 'bg-violet-500/15', text: 'text-violet-300', ring: 'focus:ring-violet-400' },
  { bg: 'bg-rose-500/15', text: 'text-rose-300', ring: 'focus:ring-rose-400' },
  { bg: 'bg-teal-500/15', text: 'text-teal-300', ring: 'focus:ring-teal-400' },
  { bg: 'bg-orange-500/15', text: 'text-orange-300', ring: 'focus:ring-orange-400' },
];
const NEUTRAL = { bg: 'bg-white/5', text: 'text-slate-400', ring: 'focus:ring-white/30' };

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
