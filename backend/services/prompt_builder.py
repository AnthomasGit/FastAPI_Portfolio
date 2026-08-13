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
# Locations carry environment-shaped profile keys, not the character wardrobe/
# face ones (KAN-41).
_LOCATION_POSITIVE_KEYS = ("environment", "architecture", "materials", "lighting", "palette")


def outfits_of(entity) -> list[dict]:
    """A character's outfits, normalised to ``[{name, items, default}]``.

    An *outfit* is the atomic unit a person actually wears, which a flat list of
    garments is not: "change the subject's clothing to black sneakers" is not an
    instruction anyone can follow, and a per-scene wardrobe swap needs a NAME to
    point at ("scene 4 uses the rain gear"), not a garment.

    Legacy profiles carrying a flat ``wardrobe`` list are read as one default
    outfit, so existing characters keep composing the exact same prompt line.
    They do lose their per-garment sheet cells — which were the redundant ones,
    since those garments are already in the base line.
    """
    profile = getattr(entity, "prompt_profile", None) or {}
    raw = profile.get("outfits")
    if raw:
        out = []
        for i, o in enumerate(raw):
            if not isinstance(o, dict):
                continue
            items = [t for t in (o.get("items") or []) if t]
            if not items:
                continue
            out.append({"name": o.get("name") or f"outfit {i + 1}",
                        "items": items,
                        "default": bool(o.get("default"))})
        if out and not any(o["default"] for o in out):
            out[0]["default"] = True   # no explicit default: the first one wins
        return out

    legacy = [t for t in (profile.get("wardrobe") or []) if t]
    return [{"name": "default", "items": legacy, "default": True}] if legacy else []


def default_outfit(entity) -> dict | None:
    """The outfit baked into the entity's base prompt line (what they wear
    unless a scene says otherwise). None when the entity has no outfits."""
    for outfit in outfits_of(entity):
        if outfit["default"]:
            return outfit
    return None


def _tokens_from(entity, keys) -> str:
    """One line for an entity: profile tokens (from `keys`) if present, else
    description, else just its name (so the subject is always referenced)."""
    profile = entity.prompt_profile or {}
    tokens = []
    for key in keys:
        tokens += [t for t in (profile.get(key) or []) if t]
    return _line(entity, tokens)


def _line(entity, tokens: list[str]) -> str:
    if tokens:
        return f"{entity.name}: " + ", ".join(tokens)
    if entity.description:
        return f"{entity.name}: {entity.description}"
    return entity.name


def _entity_tokens(entity, *, outfit: bool = True, palette: bool = True) -> str:
    """Character/prop token line: fixed appearance, the DEFAULT outfit only, and
    palette. Non-default outfits are deliberately excluded — they are alternates
    selected per scene or per sheet cell, and listing them all would describe a
    subject wearing several outfits at once.

    Clearing `outfit`/`palette` leaves the IDENTITY only, which is what a cell
    that dresses the subject in an alternate outfit needs — see entity_prompt.
    """
    profile = getattr(entity, "prompt_profile", None) or {}
    tokens = [t for t in (profile.get("appearance") or []) if t]
    if outfit:
        worn = default_outfit(entity)
        if worn:
            tokens += worn["items"]
    if palette:
        tokens += [t for t in (profile.get("palette") or []) if t]
    return _line(entity, tokens)


def _location_tokens(location) -> str:
    """Location token line (environment/architecture/materials/lighting/palette)."""
    return _tokens_from(location, _LOCATION_POSITIVE_KEYS)


def location_prompt(location) -> str:
    """Public location token line, used when attaching a location's fixed tokens
    to image generation (scene prompts and the location asset generator, KAN-41)."""
    return _location_tokens(location)


def entity_prompt(entity, *, outfit: bool = True, palette: bool = True) -> str:
    """Public single-entity prompt line (profile tokens, else description, else
    name). Used by the character-sheet builder (KAN-38) to compose per-cell
    prompts from a character's structured profile.

    Clear `outfit` for a cell that dresses the subject in an ALTERNATE outfit.
    Leaving the default outfit in asserts it as present fact while the suffix
    asks to change it, and an edit model reconciles that by compositing rather
    than replacing — measured: a charcoal suit jacket rendered on top of the
    football jersey, over the track pants it was supposed to replace.
    """
    return _entity_tokens(entity, outfit=outfit, palette=palette)


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
        lines.append("Location: " + "; ".join(_location_tokens(l) for l in locs))
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
