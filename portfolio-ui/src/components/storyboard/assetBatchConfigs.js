// One dialog, three configs — the tabs differ in what they render, not in how.
// `primaryField` is the column that means "this entity already has art", which
// is what the skip-existing checkbox filters on.
export const ASSET_BATCH_CONFIGS = {
  characters: {
    kind: 'character_sheet',
    title: 'Generate character sheets',
    blurb: 'A consistent sheet per character — angles, expressions and one cell per '
         + 'wardrobe entry, all sharing a locked seed.',
    primaryField: 'canonical_asset_image_id',
    baseImageToggle: true,
    workflow: 'krea2_turbo',
  },
  props: {
    kind: 'prop_sheet',
    title: 'Generate prop sheets',
    blurb: 'A sheet per prop — angles plus a top-down and a material close-up. '
         + 'No expression cells; a prop has no face.',
    primaryField: 'canonical_asset_image_id',
    baseImageToggle: true,
    workflow: 'krea2_turbo',
  },
  locations: {
    kind: 'location_plate',
    title: 'Generate location plates',
    blurb: 'A wide, character-free establishing plate per location, optionally '
         + 'followed by a 360 angle set rendered off it.',
    primaryField: 'plate_asset_image_id',
    anglesToggle: true,
  },
};
