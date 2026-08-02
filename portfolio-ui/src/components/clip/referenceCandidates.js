import { api } from '../../lib/api';

// Flatten a scene's linked entities into pickable clip references.
//
// Candidates come from the scene's already-linked characters/props/locations
// using each link's per-scene primary reference — that is what makes the
// upstream assets stage pay off here, instead of asking the user to re-pick
// images they already chose for this scene.
//
// Split from ReferenceSlots.jsx so that file exports components only.

export function sceneCandidates(scene) {
  if (!scene) return { subjects: [], locations: [] };

  const build = (items = [], links = [], type) =>
    items
      .map((entity) => {
        const link = links.find((l) => l.entity_id === entity.id);
        return {
          key: `${type}:${entity.id}`,
          type,
          name: entity.name,
          description: entity.description,
          referenceId: link?.reference_id || null,
          thumb: api.getLinkThumbUrl(link),
        };
      })
      // No chosen reference means no image to send to ComfyUI.
      .filter((c) => c.referenceId);

  return {
    subjects: [
      ...build(scene.characters, scene.character_links, 'character'),
      ...build(scene.props, scene.prop_links, 'prop'),
    ],
    locations: build(scene.locations, scene.location_links, 'location'),
  };
}
