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


def default_cells(character: Character) -> list[dict]:
    """Build the default cell list for a character: fixed angle + expression
    rows plus one wardrobe cell per entry in ``prompt_profile.wardrobe``."""
    cells = [dict(c) for c in ANGLE_CELLS + EXPRESSION_CELLS]
    wardrobe = (character.prompt_profile or {}).get("wardrobe") or []
    for item in wardrobe:
        if not item:
            continue
        cells.append({"slot": f"wardrobe:{item}", "suffix": f"full body, wearing {item}"})
    return cells


def _cell_prompt(base: str, suffix: str) -> str:
    suffix = (suffix or "").strip()
    return f"{base}, {suffix}" if suffix else base


async def create_character_sheet(
    character: Character,
    db: AsyncSession,
    cells: list[dict] | None = None,
) -> tuple[Batch, list[JobRecord]]:
    """Create a ``character_sheet`` batch: one job per cell, all sharing the
    character's locked seed and canonical reference image, differing only by the
    cell suffix. Appends a dependent ``contact_sheet`` job that composes the
    finished cells into a labelled grid. Returns (batch, jobs).

    Raises ValueError if the cell list is empty (router -> 422).
    """
    cells = cells if cells is not None else default_cells(character)
    cells = [c for c in cells if c and c.get("slot")]
    if not cells:
        raise ValueError("Character sheet needs at least one cell")

    project_id = character.project_id
    base_prompt = entity_prompt(character)
    profile = character.prompt_profile or {}
    # One seed shared across every cell so the sheet is one consistent subject.
    seed = resolve_seed("locked", {
        "project_id": project_id,
        "target_id": character.id,
        "locked_seed": profile.get("locked_seed"),
    })
    canonical_id = character.canonical_asset_image_id

    batch = Batch(
        project_id=project_id,
        name=f"Character sheet — {character.name}",
        kind="character_sheet",
        spec={"character_id": character.id, "seed": seed, "cells": cells},
        status="pending",
    )
    db.add(batch)
    await db.flush()

    jobs: list[JobRecord] = []
    last_cell_job: JobRecord | None = None
    for cell in cells:
        prompt = _cell_prompt(base_prompt, cell.get("suffix"))
        asset = AssetImage(
            origin_project_id=project_id,
            entity_type="character",
            kind="sheet",
            prompt=prompt,
            status="queued",
            source_asset_image_id=canonical_id,
            params={"sheet_slot": cell["slot"], "sheet_batch_id": batch.id,
                    "character_id": character.id},
        )
        db.add(asset)
        await db.flush()
        job = JobRecord(
            kind="character_sheet", status="queued", seed=seed, batch_id=batch.id,
            entity_type="asset_image", entity_id=asset.id,
            payload={
                "project_id": project_id,
                "entity_type": "character",
                "prompt": prompt,
                "seed": seed,
                "source_asset_image_id": canonical_id,
                "asset_image_id": asset.id,
                "sheet_slot": cell["slot"],
            },
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
        entity_type="character",
        kind="contact_sheet",
        prompt=f"Contact sheet — {character.name}",
        status="queued",
        params={"sheet_batch_id": batch.id, "character_id": character.id},
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
            "character_id": character.id,
            "project_id": project_id,
        },
    )
    db.add(contact_job)
    jobs.append(contact_job)

    await db.commit()
    return batch, jobs


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
    rel = f"assets/{project_id}/characters/contact_{batch_id}.png"
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
