// Which profile fields each department carries, mirroring the schema
// ai_service asks the LLM for. A location has no wardrobe and a character has
// no architecture, so the editor is driven by this table rather than by
// branches in the component.
//
// `hint` is what actually stops a profile going bad: these tokens are repeated
// in EVERY frame the subject appears in, so the guidance a user needs at the
// point of editing is "is this permanently true?", not "what is this field".

const NEGATIVE = {
  key: 'negative',
  label: 'Avoid',
  hint: 'Bare nouns — "formal wear", not "no formal wear". Most models ignore '
      + 'this entirely, so anything that MUST hold belongs in Appearance, '
      + 'stated positively ("no glasses").',
};

const PALETTE = {
  key: 'palette',
  label: 'Palette',
  hint: 'Colour tokens. Left out of sheet cells, where it drags the default '
      + 'outfit back in by colour.',
};

const SUBJECT_APPEARANCE = {
  key: 'appearance',
  label: 'Appearance',
  hint: 'Permanent physical traits only — body, face, hair, distinguishing '
      + 'marks. Never clothing, mood, or what they are doing. Test each line: '
      + 'would it still be true while they slept?',
};

export const PROFILE_FIELDS = {
  character: [SUBJECT_APPEARANCE, PALETTE, NEGATIVE],
  prop: [
    {
      key: 'appearance',
      label: 'Appearance',
      hint: 'Permanent physical traits — form, material, finish, distinguishing '
          + 'marks. Describing one face ("buttons on the front") fights any cell '
          + 'that turns the object around.',
    },
    PALETTE,
    NEGATIVE,
  ],
  location: [
    { key: 'environment', label: 'Environment', hint: 'The space itself — "gothic stone hall", "vaulted ceiling".' },
    { key: 'architecture', label: 'Architecture', hint: 'Structural and form tokens.' },
    { key: 'materials', label: 'Materials', hint: 'Surfaces and fixed set dressing — "worn flagstone", "iron sconces".' },
    { key: 'lighting', label: 'Lighting', hint: 'Fixed lighting only — "torchlight", "cold north window light".' },
    PALETTE,
    { ...NEGATIVE, hint: 'Bare nouns. Keep "people" and "characters" here so plates stay empty.' },
  ],
};

// Only characters wear outfits. An outfit is the atomic unit a person actually
// wears: the default one is baked into every prompt, and alternates are opt-in
// per sheet run and selectable per scene.
export const HAS_OUTFITS = { character: true, prop: false, location: false };

export const DEPT_ACCENT = { character: 'cast', prop: 'prop', location: 'set' };

/** Profile → { [key]: "one token per line" } for the textarea editor. */
export function profileToDraft(profile, fields) {
  const draft = {};
  for (const f of fields) draft[f.key] = ((profile || {})[f.key] || []).join('\n');
  return draft;
}

/** Textarea text → token array, trimming blanks so stray newlines don't
 *  become empty tokens that render as ", ," in a composed prompt. */
export function linesToTokens(text) {
  return (text || '').split('\n').map((t) => t.trim()).filter(Boolean);
}

/** True when a profile carries any visual token — matches the backend's
 *  has_profile(), which ignores `notes`/`locked_seed` because a profile holding
 *  only those describes nothing and still needs generating. */
export function hasProfile(profile) {
  if (!profile) return false;
  const keys = ['appearance', 'outfits', 'wardrobe', 'palette',
                'environment', 'architecture', 'materials', 'lighting'];
  return keys.some((k) => (profile[k] || []).length > 0);
}
