"""Prune stale ComfyUI outputs (Phase 1, KAN-31).

Deletes files under COMFY_OUTPUT_DIR that no live DB row references and that are
older than a cutoff — this covers both orphans (owning row gone) and the outputs
of cancelled/failed jobs (which never record a url, so they're unreferenced).

Dry-run by default: it only lists what it *would* delete. Pass --apply to
actually remove files. Not wired to any cron — run it by hand or schedule it
separately.

    python -m scripts.prune_outputs --days 7            # dry-run
    python -m scripts.prune_outputs --days 7 --apply    # actually delete
"""
import os
import argparse
import asyncio
from datetime import datetime, timedelta

DEFAULT_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")


def _iter_files(output_dir: str):
    """Yield (relpath, fullpath) for every file under output_dir."""
    for root, _dirs, files in os.walk(output_dir):
        for name in files:
            full = os.path.join(root, name)
            yield os.path.relpath(full, output_dir), full


def find_prunable(output_dir: str, referenced: set[str], cutoff: datetime) -> list[str]:
    """Relative paths safe to prune: not referenced by any DB row AND last
    modified before `cutoff` (the age floor protects in-flight generations)."""
    prunable = []
    for rel, full in _iter_files(output_dir):
        if rel in referenced:
            continue
        try:
            mtime = datetime.utcfromtimestamp(os.path.getmtime(full))
        except OSError:
            continue
        if mtime >= cutoff:
            continue  # too new — a run may still be writing it
        prunable.append(rel)
    return sorted(prunable)


def run_prune(output_dir: str, referenced: set[str], days: int, apply: bool) -> dict:
    """Compute (and optionally delete) prunable files. Deletes nothing unless
    `apply` is True. Returns {'prunable': [...], 'deleted': [...]}."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    prunable = find_prunable(output_dir, referenced, cutoff)
    deleted = []
    if apply:
        for rel in prunable:
            try:
                os.remove(os.path.join(output_dir, rel))
                deleted.append(rel)
            except OSError as e:
                print(f"[prune] could not delete {rel}: {e}")
    return {"prunable": prunable, "deleted": deleted}


async def collect_referenced(db) -> set[str]:
    """Every output-dir-relative url still referenced by a live DB row."""
    from sqlalchemy import select
    from database import GeneratedImage, AssetImage, GeneratedVideo, Asset3D

    referenced: set[str] = set()
    columns = [
        (GeneratedImage, ("image_url",)),
        (AssetImage, ("image_url",)),
        (GeneratedVideo, ("video_url",)),
        (Asset3D, ("mesh_url", "white_mesh_url", "web_mesh_url", "rigged_mesh_url")),
    ]
    for model, attrs in columns:
        rows = (await db.execute(select(model))).scalars().all()
        for row in rows:
            for attr in attrs:
                val = getattr(row, attr, None)
                if val:
                    referenced.add(val)
    return referenced


async def _main_async(args) -> None:
    from database import SessionLocal

    async with SessionLocal() as db:
        referenced = await collect_referenced(db)

    result = run_prune(args.output_dir, referenced, args.days, args.apply)
    for rel in result["prunable"]:
        prefix = "deleted" if args.apply else "would delete"
        print(f"[{prefix}] {rel}")
    verb = "Deleted" if args.apply else "Would delete"
    print(f"{verb} {len(result['prunable'])} file(s) "
          f"(referenced kept: {len(referenced)}). "
          f"{'' if args.apply else 'Dry-run — pass --apply to delete.'}")


def main() -> None:
    p = argparse.ArgumentParser(description="Prune stale ComfyUI outputs.")
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--days", type=int, default=7,
                   help="Only prune files older than this many days.")
    p.add_argument("--apply", action="store_true",
                   help="Actually delete (default is a dry-run).")
    args = p.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
