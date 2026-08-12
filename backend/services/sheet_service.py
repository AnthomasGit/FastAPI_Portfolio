"""Character sheets, contact-sheet composites, and dataset export (Phase 3).

A *character sheet* (KAN-38) is just a batch of N generations of one character
with a locked seed and per-cell prompt suffixes: front/profile/back angles, a row
of expressions, and one cell per wardrobe entry from the character's
``prompt_profile``. Each cell lands as an ``AssetImage`` tagged ``kind="sheet"``
so the existing per-project asset library renders them with no UI work.

Once the cells complete, a dependent *contact-sheet* job (KAN-39) composes them
into a single labelled grid PNG with PIL — no ComfyUI round-trip. And because a
character sheet *is* a captioned dataset, ``GET /api/characters/{id}/dataset.zip``
(KAN-40) streams the images plus matching ``.txt`` captions in the standard
LoRA-dataset layout.

The sheet template is data (``ANGLE_CELLS`` / ``EXPRESSION_CELLS`` + wardrobe),
not hardcoded branches, so it can be extended or overridden per request.
"""
import io
import os
import json
import uuid
import tempfile
import zipfile
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AssetImage, Batch, JobRecord, Character, Project
from services.seed_policy import resolve_seed
from services.prompt_builder import entity_prompt
from services.job_handlers import register_local

logger = logging.getLogger("sheet_service")

COMFY_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")

# Default sheet template. Each cell is {slot, suffix}: `slot` names the cell
# (stored in params.sheet_slot and used as the contact-sheet / caption label),
# `suffix` is appended to the character's base prompt. Data, not branches, so
# the grid can be extended here or overridden per request.
ANGLE_CELLS = [
    {"slot": "front", "suffix": "front view, full body, neutral expression"},
    {"slot": "three-quarter", "suffix": "three-quarter view, full body"},
    {"slot": "profile", "suffix": "side profile view, full body"},
    {"slot": "back", "suffix": "back view, full body"},
]
EXPRESSION_CELLS = [
    {"slot": "expr-neutral", "suffix": "head and shoulders, neutral expression"},
    {"slot": "expr-joy", "suffix": "head and shoulders, joyful expression, smiling"},
    {"slot": "expr-anger", "suffix": "head and shoulders, angry expression"},
    {"slot": "expr-fear", "suffix": "head and shoulders, fearful expression"},
]

# A prop has no face, so expression cells are meaningless for one. What a
# modeller (and an R2V reference slot) actually wants instead is a top-down and
# a material close-up.
PROP_ANGLE_CELLS = [
    {"slot": "front", "suffix": "front view, full object, plain background"},
    {"slot": "three-quarter", "suffix": "three-quarter view, full object"},
    {"slot": "side", "suffix": "side view, full object"},
    {"slot": "back", "suffix": "back view, full object"},
    {"slot": "top", "suffix": "top-down view, full object"},
    {"slot": "detail", "suffix": "extreme close-up of surface material and texture"},
]

# Per-entity-type sheet shape. `variant_key` names the prompt_profile list that
# expands into one extra cell each (a character's wardrobe, a prop's materials).
SHEET_TEMPLATES = {
    "character": {
        "cells": ANGLE_CELLS + EXPRESSION_CELLS,
        "variant_key": "wardrobe",
        "variant_suffix": "full body, wearing {item}",
        "asset_dir": "characters",
    },
    "prop": {
        "cells": PROP_ANGLE_CELLS,
        "variant_key": "materials",
        "variant_suffix": "full object, {item} finish",
        "asset_dir": "props",
    },
}

VALID_SHEET_ENTITY_TYPES = tuple(SHEET_TEMPLATES)


def default_cells(entity, entity_type: str = "character") -> list[dict]:
    """The default cell list for an entity: its type's fixed rows plus one cell
    per entry in the profile list that type varies over."""
    tpl = SHEET_TEMPLATES.get(entity_type)
    if tpl is None:
        raise ValueError(
            f"No sheet template for '{entity_type}' "
            f"(known: {', '.join(VALID_SHEET_ENTITY_TYPES)})"
        )
    cells = [dict(c) for c in tpl["cells"]]
    for item in (getattr(entity, "prompt_profile", None) or {}).get(tpl["variant_key"]) or []:
        if not item:
            continue
        cells.append({
            "slot": f"{tpl['variant_key']}:{item}",
            "suffix": tpl["variant_suffix"].format(item=item),
        })
    return cells


def _cell_prompt(base: str, suffix: str) -> str:
    suffix = (suffix or "").strip()
    return f"{base}, {suffix}" if suffix else base


async def build_sheet_jobs(
    entity,
    entity_type: str,
    batch: Batch,
    db: AsyncSession,
    *,
    cells: list[dict] | None = None,
    workflow: str | None = None,
    from_canonical: bool = True,
) -> list[JobRecord]:
    """The sheet's jobs for an existing batch, WITHOUT committing.

    Split out from create_entity_sheet so a project-wide batch can materialize
    sheets inside its own transaction — committing here would commit a
    half-built batch (create_batch flushes its Batch row first and adds jobs
    after, so a nested commit persists an incomplete graph).

    `from_canonical` picks the generation route per cell: img2img off the
    entity's canonical image (what makes a sheet actually consistent) or a fresh
    txt2img via `workflow`. It is forced off when there is no canonical image.
    """
    cells = cells if cells is not None else default_cells(entity, entity_type)
    cells = [c for c in cells if c and c.get("slot")]
    if not cells:
        raise ValueError(f"{entity_type.title()} sheet needs at least one cell")

    project_id = entity.project_id
    base_prompt = entity_prompt(entity)
    profile = getattr(entity, "prompt_profile", None) or {}
    # One seed shared across every cell so the sheet is one consistent subject.
    seed = resolve_seed("locked", {
        "project_id": project_id,
        "target_id": entity.id,
        "locked_seed": profile.get("locked_seed"),
    })
    canonical_id = entity.canonical_asset_image_id if from_canonical else None
    kind = f"{entity_type}_sheet" if entity_type != "character" else "character_sheet"

    jobs: list[JobRecord] = []
    last_cell_job: JobRecord | None = None
    for cell in cells:
        prompt = _cell_prompt(base_prompt, cell.get("suffix"))
        asset = AssetImage(
            origin_project_id=project_id,
            entity_type=entity_type,
            kind="sheet",
            prompt=prompt,
            status="queued",
            source_asset_image_id=canonical_id,
            params={"sheet_slot": cell["slot"], "sheet_batch_id": batch.id,
                    "entity_type": entity_type, "entity_id": entity.id,
                    f"{entity_type}_id": entity.id},
        )
        db.add(asset)
        await db.flush()
        payload = {
            "project_id": project_id,
            "entity_type": entity_type,
            "prompt": prompt,
            "seed": seed,
            "source_asset_image_id": canonical_id,
            "asset_image_id": asset.id,
            "sheet_slot": cell["slot"],
        }
        # Only meaningful on the txt2img route; build_sheet_cell ignores it when
        # a source image is present.
        if workflow:
            payload["workflow"] = workflow
        job = JobRecord(
            kind=kind, status="queued", seed=seed, batch_id=batch.id,
            entity_type="asset_image", entity_id=asset.id,
            payload=payload,
        )
        db.add(job)
        await db.flush()
        jobs.append(job)
        last_cell_job = job

    # Contact-sheet composite: a dependent local job. With MAX_INFLIGHT=1 the
    # cells run in creation order, so depending on the last cell means every
    # cell has finished by the time the composite runs (a failed middle cell
    # still leaves the last one to trigger us — we draw a placeholder for it).
    #
    # NB this "depend on the last cell" trick is a stand-in for a real fan-in
    # barrier and is ONLY correct while the worker runs jobs serially. Before
    # raising MAX_INFLIGHT (multi-GPU / cloud), replace this with a batch-level
    # dependency — see docs/BATCH_AUTOMATION_PLAN.md §6 "Concurrency upgrade path".
    contact_asset = AssetImage(
        origin_project_id=project_id,
        entity_type=entity_type,
        kind="contact_sheet",
        prompt=f"Contact sheet — {entity.name}",
        status="queued",
        params={"sheet_batch_id": batch.id, "entity_type": entity_type,
                "entity_id": entity.id, f"{entity_type}_id": entity.id},
    )
    db.add(contact_asset)
    await db.flush()
    contact_job = JobRecord(
        kind="contact_sheet", status="queued", batch_id=batch.id,
        entity_type="asset_image", entity_id=contact_asset.id,
        depends_on_job_id=last_cell_job.job_id if last_cell_job else None,
        payload={
            "asset_image_id": contact_asset.id,
            "sheet_batch_id": batch.id,
            "entity_type": entity_type,
            f"{entity_type}_id": entity.id,
            "project_id": project_id,
        },
    )
    db.add(contact_job)
    await db.flush()
    jobs.append(contact_job)
    return jobs


async def create_entity_sheet(
    entity,
    entity_type: str,
    db: AsyncSession,
    cells: list[dict] | None = None,
    *,
    workflow: str | None = None,
    from_canonical: bool = True,
) -> tuple[Batch, list[JobRecord]]:
    """Create a sheet batch for one entity and commit it. Returns (batch, jobs).

    The standalone entry point (POST /api/{characters,props}/{id}/sheet). A
    project-wide batch uses build_sheet_jobs directly instead, so it can put the
    jobs in its own batch and transaction.
    """
    if entity_type not in SHEET_TEMPLATES:
        raise ValueError(
            f"No sheet template for '{entity_type}' "
            f"(known: {', '.join(VALID_SHEET_ENTITY_TYPES)})"
        )
    kind = f"{entity_type}_sheet" if entity_type != "character" else "character_sheet"
    batch = Batch(
        project_id=entity.project_id,
        name=f"{entity_type.title()} sheet — {entity.name}",
        kind=kind,
        spec={"entity_type": entity_type, f"{entity_type}_id": entity.id},
        status="pending",
    )
    db.add(batch)
    await db.flush()
    jobs = await build_sheet_jobs(entity, entity_type, batch, db, cells=cells,
                                  workflow=workflow, from_canonical=from_canonical)
    batch.spec = {**batch.spec, "seed": jobs[0].seed,
                  "cells": cells if cells is not None else default_cells(entity, entity_type)}
    await db.commit()
    return batch, jobs


async def create_character_sheet(
    character: Character,
    db: AsyncSession,
    cells: list[dict] | None = None,
) -> tuple[Batch, list[JobRecord]]:
    """Back-compat alias — POST /api/characters/{id}/sheet and its tests use this."""
    return await create_entity_sheet(character, "character", db, cells)


# ── contact-sheet composite (KAN-39) ────────────────────────────────────────

async def _sheet_cells(batch_id: str, db: AsyncSession) -> list[AssetImage]:
    """The ``kind="sheet"`` AssetImages of a batch, ordered by creation."""
    rows = (await db.execute(
        select(AssetImage).where(AssetImage.kind == "sheet")
        .order_by(AssetImage.created_at.asc())
    )).scalars().all()
    return [a for a in rows if (a.params or {}).get("sheet_batch_id") == batch_id]


def compose_contact_sheet(cells: list[dict], out_path: str,
                          cell_size: int = 256, cols: int = 4,
                          label_h: int = 22) -> tuple[int, int]:
    """Compose ``cells`` into a labelled grid PNG at ``out_path``.

    Each cell is ``{"label": str, "path": str | None}``. A cell whose file is
    missing or unreadable is drawn as a placeholder rather than aborting the
    whole composite. Returns the grid (cols, rows).
    """
    from PIL import Image, ImageDraw, ImageFont

    n = len(cells)
    cols = max(1, min(cols, n)) if n else 1
    rows = (n + cols - 1) // cols if n else 1
    tile_h = cell_size + label_h
    sheet = Image.new("RGB", (cols * cell_size, rows * tile_h), (32, 32, 32))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover - font always present in practice
        font = None

    for i, cell in enumerate(cells):
        cx = (i % cols) * cell_size
        cy = (i // cols) * tile_h
        path = cell.get("path")
        img = None
        if path and os.path.exists(path):
            try:
                img = Image.open(path).convert("RGB")
            except Exception:
                img = None
        if img is not None:
            img.thumbnail((cell_size, cell_size))
            ox = cx + (cell_size - img.width) // 2
            oy = cy + (cell_size - img.height) // 2
            sheet.paste(img, (ox, oy))
        else:
            # Placeholder box for a missing/failed cell.
            draw.rectangle([cx + 4, cy + 4, cx + cell_size - 4, cy + cell_size - 4],
                           outline=(120, 120, 120), width=2)
            draw.text((cx + 10, cy + cell_size // 2), "missing", fill=(180, 180, 180), font=font)
        draw.text((cx + 4, cy + cell_size + 4), str(cell.get("label", "")),
                  fill=(230, 230, 230), font=font)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    sheet.save(out_path, "PNG")
    return cols, rows


async def run_contact_sheet(payload: dict, db: AsyncSession) -> dict:
    """Local job handler (KAN-39): compose the finished sheet cells of a batch
    into a contact sheet PNG, store it on the contact_sheet AssetImage row."""
    batch_id = payload["sheet_batch_id"]
    asset_id = payload["asset_image_id"]
    project_id = payload.get("project_id")

    cells = await _sheet_cells(batch_id, db)
    labeled = [
        {
            "label": (a.params or {}).get("sheet_slot", ""),
            "path": os.path.join(COMFY_OUTPUT_DIR, a.image_url) if a.image_url else None,
        }
        for a in cells
    ]
    # Older payloads carry no entity_type; they were all characters.
    asset_dir = SHEET_TEMPLATES.get(
        payload.get("entity_type", "character"), SHEET_TEMPLATES["character"]
    )["asset_dir"]
    rel = f"assets/{project_id}/{asset_dir}/contact_{batch_id}.png"
    out_path = os.path.join(COMFY_OUTPUT_DIR, rel)
    compose_contact_sheet(labeled, out_path)

    asset = await db.get(AssetImage, asset_id)
    if asset is not None:
        asset.status = "completed"
        asset.image_url = rel
        await db.commit()
    return {"image_url": rel}


# ── dataset export (KAN-40) ─────────────────────────────────────────────────

def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (name or ""))


def _caption(asset: AssetImage) -> str:
    """LoRA caption for a cell: its full prompt (already profile + slot suffix)."""
    return asset.prompt or ""


async def build_dataset_zip(character: Character, db: AsyncSession) -> str | None:
    """Write a LoRA-ready dataset zip for a character to a temp file and return
    its path (caller streams then deletes), or None if the character has no
    completed sheet images.

    Layout: ``<i>_<slot>.png`` + matching ``<i>_<slot>.txt`` caption side by
    side, plus a ``metadata.json`` tracing project/character/seed/profile. The
    zip is built on disk, never buffered whole in memory.
    """
    rows = (await db.execute(
        select(AssetImage).where(AssetImage.kind == "sheet")
        .order_by(AssetImage.created_at.asc())
    )).scalars().all()
    cells = [
        a for a in rows
        if (a.params or {}).get("character_id") == character.id
        and a.status == "completed" and a.image_url
    ]
    if not cells:
        return None

    project = await db.get(Project, character.project_id)
    metadata = {
        "project_id": character.project_id,
        "project_title": project.title if project else None,
        "character_id": character.id,
        "character_name": character.name,
        "prompt_profile": character.prompt_profile,
        "images": [],
    }

    fd, tmp_path = tempfile.mkstemp(suffix=".zip", prefix="dataset_")
    os.close(fd)
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, asset in enumerate(cells):
            slot = _safe((asset.params or {}).get("sheet_slot", f"cell{i}"))
            base = f"{i:02d}_{slot}"
            src = os.path.join(COMFY_OUTPUT_DIR, asset.image_url)
            try:
                zf.write(src, f"{base}.png")
            except OSError:
                logger.warning("dataset: image missing on disk, skipping %s", asset.image_url)
                continue
            zf.writestr(f"{base}.txt", _caption(asset))
            metadata["images"].append({"file": f"{base}.png", "slot": slot,
                                       "caption": _caption(asset)})
        # Seed is shared across the sheet; read it off any cell's job payload.
        if metadata["images"]:
            job = (await db.execute(
                select(JobRecord).where(
                    JobRecord.entity_type == "asset_image",
                    JobRecord.entity_id == cells[0].id,
                ).order_by(JobRecord.created_at.desc())
            )).scalars().first()
            if job is not None:
                metadata["seed"] = job.seed or (job.payload or {}).get("seed")
        zf.writestr("metadata.json", json.dumps(metadata, indent=2, default=str))

    return tmp_path


register_local("contact_sheet", run_contact_sheet)
