"""Scene prompt composition (Phase 2, KAN-34).

Owns all prompt building. Replaces the old free-text description concatenation
in comfyui_service.construct_prompt with a deterministic composition from each
entity's structured `prompt_profile` (falling back to its description, then its
name), the project's `style_profile` (falling back to the legacy style tail),
and a separately-emitted negative prompt.

Deterministic by construction: entities are sorted by name and profile token
lists keep their order, so identical inputs yield a byte-identical prompt —
which matters for reproducibility.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    Scene, Character, Location, Prop, Project,
    scene_characters, scene_locations, scene_props,
)

LEGACY_STYLE_TAIL = "cinematic, film still, professional lighting, high detail, 4K"
_PROFILE_POSITIVE_KEYS = ("appearance", "wardrobe", "palette")


def _entity_tokens(entity) -> str:
    """One line for an entity: profile tokens if present, else description, else
    just its name (so the subject is always referenced)."""
    profile = entity.prompt_profile or {}
    tokens = []
    for key in _PROFILE_POSITIVE_KEYS:
        tokens += [t for t in (profile.get(key) or []) if t]
    if tokens:
        return f"{entity.name}: " + ", ".join(tokens)
    if entity.description:
        return f"{entity.name}: {entity.description}"
    return entity.name


def _style_tokens(project) -> str:
    sp = getattr(project, "style_profile", None) if project else None
    if sp:
        parts = [sp.get(k) for k in ("film_stock", "lens", "grade", "lighting")]
        parts = [p for p in parts if p]
        parts += [t for t in (sp.get("extra") or []) if t]
        if parts:
            return ", ".join(parts)
    return LEGACY_STYLE_TAIL


def _negatives(entities) -> str:
    """Union of every entity profile's negative tokens, first-seen order, deduped."""
    seen: list[str] = []
    for e in entities:
        for t in (e.prompt_profile or {}).get("negative") or []:
            if t and t not in seen:
                seen.append(t)
    return ", ".join(seen)


def build_prompt(scene, characters, locations, props, project) -> tuple[str, str]:
    """Compose (positive, negative) from already-loaded rows.

    Section order is fixed: scene action → character → location → prop → project
    style; negatives are returned separately (for the negative_prompt node).
    """
    chars = sorted(characters, key=lambda c: c.name or "")
    locs = sorted(locations, key=lambda l: l.name or "")
    prps = sorted(props, key=lambda p: p.name or "")

    lines = []
    if scene.slugline:
        lines.append(f"Scene: {scene.slugline}")
    if scene.screenplay:
        lines.append(f"Action: {scene.screenplay}")
    if chars:
        lines.append("Characters: " + "; ".join(_entity_tokens(c) for c in chars))
    if locs:
        lines.append("Location: " + "; ".join(_entity_tokens(l) for l in locs))
    if prps:
        lines.append("Props: " + "; ".join(_entity_tokens(p) for p in prps))
    lines.append("Style: " + _style_tokens(project))

    positive = "\n".join(lines)
    negative = _negatives(chars + locs + prps)
    return positive, negative


async def build_scene_prompt(scene_id: str, db: AsyncSession) -> tuple[str, str]:
    """Load a scene's entities + project and compose (positive, negative)."""
    scene = await db.get(Scene, scene_id)
    if not scene:
        return "", ""

    characters = (await db.execute(
        select(Character).join(scene_characters).where(scene_characters.c.scene_id == scene_id)
    )).scalars().all()
    locations = (await db.execute(
        select(Location).join(scene_locations).where(scene_locations.c.scene_id == scene_id)
    )).scalars().all()
    props = (await db.execute(
        select(Prop).join(scene_props).where(scene_props.c.scene_id == scene_id)
    )).scalars().all()
    project = await db.get(Project, scene.project_id)

    return build_prompt(scene, characters, locations, props, project)
