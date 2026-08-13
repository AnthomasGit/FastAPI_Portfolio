"""Identity base plates — the one image a character's or prop's generations edit from.

Sheets run img2img through an image-EDIT model, which preserves whatever source
it is handed. Resolving that source as "the entity's newest reference" meant
editing whatever happened to be generated last: measured, a character sheet
edited a living-room scene still and returned the subject still sitting on the
sofa in every cell.

A *base plate* is that source, made deliberately: a plain txt2img of the subject
alone, front-on, on a neutral backdrop, from its ``prompt_profile`` tokens. It
is stored on ``<entity>.base_asset_image_id`` and is orthogonal to the per-scene
primary — see migration 0028.

Plates are generated automatically. `ensure_base_plate` returns the plate job
when one had to be created, and callers make their own jobs depend on it; a
character that already has a plate costs nothing.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from database import AssetImage, JobRecord, Character, Prop
from services.prompt_builder import entity_prompt
from services.job_handlers import register, build_asset_txt2img, _finalize_row

ENTITY_MODELS = {"character": Character, "prop": Prop}

# Fresh renders default to Krea2 rather than the global txt2img default: the
# plate is the one image in the whole sheet pipeline that is NOT an edit, so it
# sets the ceiling for every cell derived from it.
DEFAULT_PLATE_WORKFLOW = "krea2_turbo"

# Appended to the entity's tokens so the plate is a clean, isolated subject —
# the qualities that make an edit source usable. Data, tuned in one place.
CHARACTER_PLATE_FRAMING = (
    "full body portrait, standing upright, facing the camera directly, "
    "full body visible head to feet, neutral expression, arms at sides, "
    "plain light grey studio backdrop, evenly lit, no props, no furniture, "
    "no other people"
)
PROP_PLATE_FRAMING = (
    "product photograph of the object alone, three-quarter view, "
    "the whole object centred and fully visible, plain light grey studio "
    "backdrop, evenly lit, no hands, no people, no other objects"
)
PLATE_FRAMING = {"character": CHARACTER_PLATE_FRAMING, "prop": PROP_PLATE_FRAMING}


def build_plate_prompt(entity, entity_type: str) -> str:
    """The plate's prompt: identity tokens plus the default outfit, then framing.

    The default outfit is deliberately INCLUDED. Every angle cell edits this
    plate, and a plate already wearing the right clothes leaves those cells with
    only a rotation to perform — the one operation this model does reliably.
    Alternate-outfit cells strip the outfit on their own side instead.
    """
    framing = PLATE_FRAMING.get(entity_type, CHARACTER_PLATE_FRAMING)
    return f"{entity_prompt(entity, palette=False)}, {framing}"


async def build_plate_job(entity, entity_type: str, db: AsyncSession, *,
                          workflow: str | None = None,
                          batch=None, seed: int | None = None) -> tuple[JobRecord, str]:
    """Create the plate's AssetImage + job WITHOUT committing.

    Returns (job, asset_image_id). The asset id is known up front, so a caller
    can point dependent jobs at it before it has rendered.
    """
    prompt = build_plate_prompt(entity, entity_type)
    asset = AssetImage(
        origin_project_id=entity.project_id,
        entity_type=entity_type,
        kind="base_plate",
        prompt=prompt,
        status="queued",
        params={"entity_type": entity_type, "entity_id": entity.id,
                f"{entity_type}_id": entity.id},
    )
    db.add(asset)
    await db.flush()

    job = JobRecord(
        kind="base_plate", status="queued", seed=seed,
        batch_id=getattr(batch, "id", None),
        entity_type="asset_image", entity_id=asset.id,
        payload={
            "project_id": entity.project_id,
            "entity_type": entity_type,
            "entity_id": entity.id,
            "prompt": prompt,
            "seed": seed,
            "workflow": workflow or DEFAULT_PLATE_WORKFLOW,
            "asset_image_id": asset.id,
        },
    )
    db.add(job)
    await db.flush()
    return job, asset.id


async def ensure_base_plate(entity, entity_type: str, db: AsyncSession, *,
                            workflow: str | None = None, batch=None,
                            seed: int | None = None) -> tuple[str | None, JobRecord | None]:
    """(base_asset_image_id, plate_job_or_None) for an entity, generating one if
    it has none.

    The returned job is None when a plate already exists — the caller then has
    nothing to depend on. Does NOT commit.
    """
    existing = getattr(entity, "base_asset_image_id", None)
    if existing and await db.get(AssetImage, existing) is not None:
        return existing, None
    job, asset_id = await build_plate_job(entity, entity_type, db,
                                          workflow=workflow, batch=batch, seed=seed)
    return asset_id, job


async def on_complete_base_plate(payload: dict, outputs: dict, db: AsyncSession) -> None:
    """Finalize the plate's AssetImage, then point its entity at it.

    Deliberately does NOT publish a Reference. A plate is a working source for
    generation, not a look to show in a scene; publishing it would make it the
    newest reference and silently become every scene's inherited image.
    """
    asset_id = payload.get("asset_image_id")
    await _finalize_row(AssetImage, asset_id, payload, db)

    model = ENTITY_MODELS.get(payload.get("entity_type") or "")
    entity_id = payload.get("entity_id")
    if model is None or not entity_id or not asset_id:
        return
    entity = await db.get(model, entity_id)
    if entity is not None:
        entity.base_asset_image_id = asset_id
        await db.commit()


register("base_plate", build_asset_txt2img, on_complete_base_plate)
