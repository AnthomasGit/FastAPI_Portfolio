"""Background job worker (Phase 0, KAN-20).

The core of Phase 0: generation advances without a browser polling. A single
async loop claims queued :class:`JobRecord` rows, submits them to ComfyUI via
the registered handler, polls ``/history`` to a terminal state, runs the
handler's ``on_complete``, and writes the final status — all server-side.

ComfyUI is single-GPU and serialises work, so ``MAX_INFLIGHT`` is about *pacing*
(default 1), not parallelism: the win is that no human has to sit in the loop.

Retry/backoff and dependency/scheduling ordering are layered on in KAN-21/KAN-22;
this task keeps the loop minimal — claim, run, finalize, mark failed on error.
"""
import os
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database import JobRecord, SessionLocal
from services.comfyui_client import submit, poll
from services.job_handlers import HANDLERS

logger = logging.getLogger("job_worker")

MAX_INFLIGHT = int(os.environ.get("MAX_INFLIGHT", "1"))
WORKER_ENABLED = os.environ.get("WORKER_ENABLED", "true").lower() not in ("0", "false", "no")
WORKER_TICK_INTERVAL = float(os.environ.get("WORKER_TICK_INTERVAL", "2.0"))
JOB_POLL_INTERVAL = float(os.environ.get("JOB_POLL_INTERVAL", "2.0"))
# KAN-21 formalises this; the loop already needs a ceiling so a job that never
# appears in /history is not polled forever.
JOB_POLL_TIMEOUT = float(os.environ.get("JOB_POLL_TIMEOUT", "600"))
# Exponential backoff base (seconds): a job's Nth retry waits base * 2**(N-1).
JOB_RETRY_BACKOFF_BASE = float(os.environ.get("JOB_RETRY_BACKOFF_BASE", "10"))

TERMINAL = ("completed", "failed", "cancelled")


def _is_postgres(db: AsyncSession) -> bool:
    try:
        return db.bind.dialect.name == "postgresql"
    except Exception:
        return False


async def claim_jobs(db: AsyncSession, limit: int, now: datetime | None = None) -> list[JobRecord]:
    """Atomically move up to ``limit`` ready queued jobs to ``running``.

    Ready = queued, ``scheduled_after`` in the past (or null), and its
    ``depends_on_job_id`` (if any) already completed. Ordered by priority (high
    first) then creation time. Race-safe on Postgres via ``FOR UPDATE SKIP
    LOCKED``; the SQLite test path relies on single-writer semantics instead
    (the clause is unsupported there). ``now`` is injectable so tests can drive
    deferred scheduling without sleeping.
    """
    if limit <= 0:
        return []
    now = now or datetime.utcnow()
    completed_ids = select(JobRecord.job_id).where(JobRecord.status == "completed")
    stmt = (
        select(JobRecord)
        .where(
            JobRecord.status == "queued",
            or_(JobRecord.scheduled_after.is_(None), JobRecord.scheduled_after <= now),
            or_(
                JobRecord.depends_on_job_id.is_(None),
                JobRecord.depends_on_job_id.in_(completed_ids),
            ),
        )
        .order_by(JobRecord.priority.desc(), JobRecord.created_at.asc())
        .limit(limit)
    )
    if _is_postgres(db):
        stmt = stmt.with_for_update(skip_locked=True)

    jobs = list((await db.execute(stmt)).scalars().all())
    for job in jobs:
        job.status = "running"
        job.started_at = now
        job.attempts = (job.attempts or 0) + 1
        logger.info("job %s (%s) claimed -> running (attempt %s)",
                    job.job_id, job.kind, job.attempts)
    await db.commit()
    return jobs


async def resolve_parent_refs(db: AsyncSession, payload: dict, parent_job_id: str) -> dict:
    """Resolve ``{"$from_parent": "<attr>"}`` payload values against the parent job.

    A chained step's input is the previous step's output, but that filename only
    exists once the parent has run — so the dependent stores a placeholder that
    is resolved here, at build time. ``<attr>`` names a column on the parent
    JobRecord (typically ``image_url``). Returns a new payload; non-placeholder
    values pass through untouched.
    """
    parent = await db.get(JobRecord, parent_job_id)
    resolved = {}
    for key, value in payload.items():
        if isinstance(value, dict) and "$from_parent" in value:
            attr = value["$from_parent"]
            resolved[key] = getattr(parent, attr, None) if parent is not None else None
        else:
            resolved[key] = value
    return resolved


async def _poll_until_done(prompt_id: str) -> dict:
    waited = 0.0
    while True:
        result = await poll(prompt_id)
        if result["status"] in ("completed", "error"):
            return result
        if waited >= JOB_POLL_TIMEOUT:
            return {"status": "error", "outputs": None, "reason": "poll_timeout"}
        await asyncio.sleep(JOB_POLL_INTERVAL)
        waited += JOB_POLL_INTERVAL


class JobWorker:
    def __init__(self, session_factory=SessionLocal, max_inflight: int | None = None,
                 retry_backoff_base: float | None = None):
        self.session_factory = session_factory
        self.max_inflight = MAX_INFLIGHT if max_inflight is None else max_inflight
        self.retry_backoff_base = (
            JOB_RETRY_BACKOFF_BASE if retry_backoff_base is None else retry_backoff_base
        )
        self._inflight: set[str] = set()
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._run())
        logger.info("job worker started (MAX_INFLIGHT=%s)", self.max_inflight)

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Any job this worker claimed but did not finish reverts to queued so a
        # restart re-runs it rather than leaving it stuck in `running`.
        await self._requeue_inflight()
        logger.info("job worker stopped")

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self.tick()
            except Exception:  # never let one bad tick kill the loop
                logger.exception("job worker tick failed")
            await asyncio.sleep(WORKER_TICK_INTERVAL)

    async def tick(self) -> int:
        """Claim and process up to the free slot count. Returns jobs processed."""
        free = self.max_inflight - len(self._inflight)
        if free <= 0:
            return 0
        async with self.session_factory() as db:
            jobs = await claim_jobs(db, free)
        if not jobs:
            return 0
        for job in jobs:
            self._inflight.add(job.job_id)
        await asyncio.gather(*(self._process(job.job_id) for job in jobs))
        return len(jobs)

    async def _process(self, job_id: str) -> None:
        try:
            async with self.session_factory() as db:
                job = await db.get(JobRecord, job_id)
                if job is None:
                    return
                handler = HANDLERS.get(job.kind)
                if handler is None:
                    job.status = "failed"
                    job.error = f"no handler for kind {job.kind!r}"
                    job.finished_at = datetime.utcnow()
                    await db.commit()
                    logger.error("job %s failed: %s", job_id, job.error)
                    return

                # Note: payload deliberately carries no job_id, so build_workflow
                # mints a fresh output prefix on every attempt (idempotent retry).
                payload = dict(job.payload or {})
                if job.depends_on_job_id:
                    payload = await resolve_parent_refs(db, payload, job.depends_on_job_id)
                try:
                    workflow, meta = await handler.build_workflow(payload, db)
                    prompt_id = await submit(workflow)
                    # Rewrite the winning path on the job row each attempt so a
                    # successful retry's output — not the first attempt's — wins.
                    job.prompt_id = prompt_id
                    job.image_url = meta.get("image_url")
                    await db.commit()
                    logger.info("job %s (%s) submitted prompt_id=%s",
                                job_id, job.kind, prompt_id)

                    result = await _poll_until_done(prompt_id)

                    if result["status"] == "completed":
                        merged = {**payload, **meta}
                        await handler.on_complete(merged, result.get("outputs") or {}, db)
                        job.status = "completed"
                        job.finished_at = datetime.utcnow()
                        await db.commit()
                        logger.info("job %s (%s) completed", job_id, job.kind)
                    else:
                        await self._handle_failure(
                            db, job, result.get("reason") or "ComfyUI reported an error"
                        )
                except Exception as e:
                    await self._handle_failure(db, job, str(e))
        finally:
            self._inflight.discard(job_id)

    async def _handle_failure(self, db: AsyncSession, job: JobRecord, error: str) -> None:
        """Requeue with exponential backoff until max_attempts, then fail.

        `attempts` was already incremented at claim time, so it equals the number
        of attempts made so far.
        """
        attempts = job.attempts or 0
        max_attempts = job.max_attempts or 1
        job.error = error
        job.prompt_id = None
        job.started_at = None
        if attempts < max_attempts:
            delay = self.retry_backoff_base * (2 ** (attempts - 1)) if attempts > 0 else 0
            job.status = "queued"
            job.scheduled_after = datetime.utcnow() + timedelta(seconds=delay)
            logger.warning("job %s (%s) attempt %s/%s failed (%s); retry in %.0fs",
                           job.job_id, job.kind, attempts, max_attempts, error, delay)
        else:
            job.status = "failed"
            job.finished_at = datetime.utcnow()
            logger.error("job %s (%s) failed permanently after %s attempts: %s",
                         job.job_id, job.kind, attempts, error)
            # Dependents can never run now — cancel them (and their dependents)
            # rather than leave them queued forever.
            await self._cancel_dependents(db, job.job_id)
        await db.commit()

    async def _cancel_dependents(self, db: AsyncSession, failed_job_id: str) -> None:
        """Cancel every transitive dependent of a terminally-failed job."""
        frontier = [failed_job_id]
        while frontier:
            parent_id = frontier.pop()
            deps = (
                await db.execute(
                    select(JobRecord).where(JobRecord.depends_on_job_id == parent_id)
                )
            ).scalars().all()
            for dep in deps:
                if dep.status in ("queued", "running"):
                    dep.status = "cancelled"
                    dep.error = f"upstream job {parent_id} failed"
                    dep.finished_at = datetime.utcnow()
                    frontier.append(dep.job_id)
                    logger.warning("job %s cancelled: upstream %s failed",
                                   dep.job_id, parent_id)

    async def _requeue_inflight(self) -> None:
        if not self._inflight:
            return
        ids = list(self._inflight)
        async with self.session_factory() as db:
            rows = (
                await db.execute(select(JobRecord).where(JobRecord.job_id.in_(ids)))
            ).scalars().all()
            for job in rows:
                if job.status == "running":
                    job.status = "queued"
                    job.started_at = None
                    logger.info("job %s reverted running -> queued on shutdown", job.job_id)
            await db.commit()
        self._inflight.clear()
