"""Batch presets (Phase 5, KAN-48).

CRUD over saved batch specs plus `run_preset`, which merges optional run-time
overrides onto a *copy* of the stored spec and instantiates a batch through the
same `assemble_batch` path as POST /api/batches — so a preset run and a direct
post from the same spec produce an identical batch. The stored spec is never
mutated by a run.
"""
import copy

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database import BatchPreset
from services.batch_service import assemble_batch


def serialize(preset: BatchPreset) -> dict:
    return {
        "id": preset.id,
        "project_id": preset.project_id,
        "name": preset.name,
        "spec": preset.spec,
        "created_at": preset.created_at.isoformat() if preset.created_at else None,
    }


async def create_preset(name: str, spec: dict, project_id: str | None, db: AsyncSession) -> BatchPreset:
    preset = BatchPreset(name=name, spec=spec, project_id=project_id)
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


async def get_preset(preset_id: str, db: AsyncSession) -> BatchPreset | None:
    return (await db.execute(select(BatchPreset).where(BatchPreset.id == preset_id))).scalars().first()


async def list_presets(project_id: str | None, db: AsyncSession) -> list[BatchPreset]:
    """A project's own presets plus the global (null-project) ones; when no
    project is given, every preset."""
    stmt = select(BatchPreset)
    if project_id is not None:
        stmt = stmt.where(or_(BatchPreset.project_id == project_id, BatchPreset.project_id.is_(None)))
    stmt = stmt.order_by(BatchPreset.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())


async def update_preset(preset: BatchPreset, name: str | None, spec: dict | None, db: AsyncSession) -> BatchPreset:
    if name is not None:
        preset.name = name
    if spec is not None:
        preset.spec = spec
    await db.commit()
    await db.refresh(preset)
    return preset


async def delete_preset(preset: BatchPreset, db: AsyncSession) -> None:
    await db.delete(preset)
    await db.commit()


def merge_spec(spec: dict, overrides: dict) -> dict:
    """Overrides shallow-merged over a deep copy of the stored spec. `params`
    (a nested dict) is merged key-wise so an override can tweak one knob without
    dropping the rest. The original spec is left untouched."""
    merged = copy.deepcopy(spec)
    for key, value in (overrides or {}).items():
        if key == "params" and isinstance(value, dict):
            merged_params = {**(merged.get("params") or {}), **value}
            merged["params"] = merged_params
        else:
            merged[key] = value
    return merged


async def run_preset(preset: BatchPreset, overrides: dict, db: AsyncSession) -> dict:
    """Instantiate a batch from the preset with run-time overrides applied. The
    stored preset.spec is not mutated."""
    spec = merge_spec(preset.spec, overrides)
    return await assemble_batch(spec, db)
