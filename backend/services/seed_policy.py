"""Seed policy (Phase 2, KAN-35).

Three ways to pick a generation seed, so runs are reproducible and variant
sweeps are deterministic:

- ``random``  — a fresh random seed (today's behaviour, the back-compat default).
- ``locked``  — the entity's ``prompt_profile.locked_seed``, else the batch-level
  base seed, else random. Pins a subject to one look.
- ``derived`` — a *stable* seed from (project_id, target_id, variant_index) via
  SHA-256, so the same inputs always yield the same seed across processes and a
  variant sweep 0..N is deterministic and distinct.

The resolved seed is written onto the job payload (and the owning row's params)
so a past generation can be reproduced exactly rather than recomputed.
"""
import random
import hashlib

# Matches the range the image services have always used (KSampler/RandomNoise
# accept far larger, but this keeps every policy within one safe band).
SEED_MAX = 1_000_000_000_000_000

VALID_POLICIES = {"random", "locked", "derived"}


def _derived_seed(project_id: str, target_id: str, variant_index: int) -> int:
    key = f"{project_id or ''}|{target_id or ''}|{variant_index or 0}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest, 16) % SEED_MAX + 1  # 1..SEED_MAX


def resolve_seed(policy: str | None, context: dict) -> int:
    """Resolve a concrete seed for one job.

    ``context`` may carry: project_id, target_id, variant_index, locked_seed
    (from the entity's profile), base_seed (batch-level).
    """
    policy = policy or "random"
    if policy == "random":
        return random.randint(1, SEED_MAX)
    if policy == "locked":
        return (
            context.get("locked_seed")
            or context.get("base_seed")
            or random.randint(1, SEED_MAX)
        )
    if policy == "derived":
        return _derived_seed(
            context.get("project_id"),
            context.get("target_id"),
            context.get("variant_index", 0),
        )
    raise ValueError(f"Unknown seed policy '{policy}' (expected one of {sorted(VALID_POLICIES)})")
