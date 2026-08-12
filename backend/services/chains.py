"""Named job chains (Phase 5, KAN-47).

A chain is an ordered list of stage templates run as a dependency graph: each
stage's input is the previous stage's output, wired through the Phase-0
``depends_on_job_id`` link and the ``{"$from_parent": "<attr>"}`` payload
convention (resolved by the worker at build time). Declaring pipelines here
means "still → polish → colour-match" is one batch spec instead of hand-driven
submits, and the worker's existing cascade-cancel already isolates a mid-chain
failure to that target's own downstream jobs.

Stage availability is *derived*: a stage is runnable only if its job kind has a
registered handler and (when it names one) its workflow graph exists on disk.
Several canonical stages — upscale/refine, face-fix, dataset-export — have no
exported ComfyUI graph or job kind yet, so the chains that use them are declared
here but report as unavailable; ``validate_chain`` rejects a batch naming one,
at request time, naming exactly what still needs exporting (KAN-47 note). The
chains light up automatically once those pieces land, no code change here.
"""
from dataclasses import dataclass, field

from services.workflow_registry import build_registry


@dataclass(frozen=True)
class Stage:
    """One step of a chain.

    kind          — the job kind (must have a registered handler to be runnable).
    workflow      — the ComfyUI graph the stage runs, if it pins one; None lets
                    the kind's handler pick its default graph. When set, the
                    graph file must exist for the stage to be available.
    parent_input  — payload key that receives the previous stage's output via
                    ``{"$from_parent": "image_url"}``. None on the root stage.
    label         — human label for the UI.
    """
    kind: str
    workflow: str | None = None
    parent_input: str | None = None
    label: str = ""


@dataclass(frozen=True)
class Chain:
    name: str
    label: str
    stages: tuple[Stage, ...]
    description: str = ""


# The canonical chains (docs/BATCH_AUTOMATION_PLAN.md Phase 5). Stages whose
# `workflow`/`kind` do not exist yet are declared anyway; chain_availability
# surfaces them and validate_chain refuses to run the chain until they land.
CHAINS: dict[str, Chain] = {
    "still_polish": Chain(
        name="still_polish",
        label="Still → polish → colour-match",
        description="Generate a scene still, upscale/refine it, then colour-match to the key frame.",
        stages=(
            Stage("scene_image", label="Scene still"),
            # No upscale/refine graph exported yet.
            Stage("upscale", workflow="image_upscale_refine", parent_input="image", label="Upscale / refine"),
            Stage("color_match", parent_input="source", label="Colour match"),
        ),
    ),
    # Named still_i2v_polish, NOT shot_clip: `shot_clip` is now a job kind (the
    # native per-shot MiniMax H3 reference-to-video render), and chain names share
    # a flat namespace with job kinds in _known_kinds(). This chain is the
    # different, older route — animate an already-approved beauty-pass still —
    # so it stays declared rather than being deleted.
    "still_i2v_polish": Chain(
        name="still_i2v_polish",
        label="Still → i2v clip → face-fix",
        description="Animate an approved still to a clip, then run a face-restoration pass.",
        stages=(
            Stage("scene_image", label="Scene still"),
            Stage("video", workflow="video_ltx_i2v", parent_input="image", label="Image-to-video clip"),
            # No face-fix graph exported yet.
            Stage("face_fix", workflow="image_face_fix", parent_input="image", label="Face-fix pass"),
        ),
    ),
    "character_kit": Chain(
        name="character_kit",
        label="Canonical → sheet → dataset",
        description="Generate a canonical character image, expand to a sheet, export a captioned dataset.",
        stages=(
            Stage("asset_txt2img", label="Canonical image"),
            Stage("character_sheet", parent_input="image", label="Character sheet"),
            # Dataset export is not a job kind yet (KAN-40 ships the zip endpoint).
            Stage("dataset_export", parent_input="image", label="Dataset export"),
        ),
    ),
}


def get_chain(name: str) -> Chain | None:
    return CHAINS.get(name)


def _known_kinds() -> set[str]:
    """Registered job-kind handlers. Imported lazily: importing the handler
    registry pulls in the service modules, and doing it at call time keeps this
    module cheap to import (and avoids an import cycle through batch_service)."""
    from services.job_handlers import HANDLERS, LOCAL_HANDLERS
    return set(HANDLERS) | set(LOCAL_HANDLERS)


def stage_missing_reason(stage: Stage, known_kinds: set[str], graphs: set[str]) -> str | None:
    """Why a stage can't run yet, or None if it's available. Names every missing
    piece — both the job kind and the workflow JSON — so the operator knows
    exactly what to export."""
    reasons = []
    if stage.kind not in known_kinds:
        reasons.append(f"job kind '{stage.kind}' has no handler")
    if stage.workflow is not None and stage.workflow not in graphs:
        reasons.append(f"workflow '{stage.workflow}' is not exported")
    return "; ".join(reasons) if reasons else None


def chain_availability(name: str) -> dict:
    """`{available, missing: [{stage, reason}], ...}` for a chain."""
    chain = CHAINS.get(name)
    if chain is None:
        return {"name": name, "available": False, "missing": [{"stage": name, "reason": "unknown chain"}]}
    known_kinds = _known_kinds()
    graphs = set(build_registry())
    missing = []
    for stage in chain.stages:
        reason = stage_missing_reason(stage, known_kinds, graphs)
        if reason:
            missing.append({"stage": stage.label or stage.kind, "reason": reason})
    return {
        "name": chain.name,
        "label": chain.label,
        "description": chain.description,
        "available": not missing,
        "stages": [{"kind": s.kind, "workflow": s.workflow, "label": s.label} for s in chain.stages],
        "missing": missing,
    }


def list_chains() -> list[dict]:
    return [chain_availability(name) for name in CHAINS]


def validate_chain(name: str) -> Chain:
    """Return the chain, or raise ValueError naming what still needs exporting.

    Raised before any job is created, so an unrunnable chain half-builds nothing
    (KAN-47 acceptance)."""
    chain = CHAINS.get(name)
    if chain is None:
        raise ValueError(f"Unknown chain '{name}'. Known chains: {', '.join(sorted(CHAINS))}.")
    info = chain_availability(name)
    if not info["available"]:
        reasons = "; ".join(f"{m['stage']}: {m['reason']}" for m in info["missing"])
        raise ValueError(
            f"Chain '{name}' cannot run yet — {reasons}. "
            f"Export the missing workflow(s)/job kind(s) first."
        )
    return chain
