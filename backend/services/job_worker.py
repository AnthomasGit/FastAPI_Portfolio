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
from datetime import datetime

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

TERMINAL = ("completed", "failed", "cancelled")


def _is_postgres(db: AsyncSession) -> bool:
    try:
        return db.bind.dialect.name == "postgresql"
    except Exception:
        return False


async def claim_jobs(db: AsyncSession, limit: int) -> list[JobRecord]:
    """Atomically move up to ``limit`` ready queued jobs to ``running``.

    Ready = queued and ``scheduled_after`` in the past (or null). Ordered by
    priority (high first) then creation time. Race-safe on Postgres via
    ``FOR UPDATE SKIP LOCKED``; the SQLite test path relies on single-writer
    semantics instead (the clause is unsupported there).
    """
    if limit <= 0:
        return []
    now = datetime.utcnow()
    stmt = (
        select(JobRecord)
        .where(
            JobRecord.status == "queued",
            or_(JobRecord.scheduled_after.is_(None), JobRecord.scheduled_after <= now),
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
    def __init__(self, session_factory=SessionLocal, max_inflight: int | None = None):
        self.session_factory = session_factory
        self.max_inflight = MAX_INFLIGHT if max_inflight is None else max_inflight
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

                payload = dict(job.payload or {})
                try:
                    workflow, meta = await handler.build_workflow(payload, db)
                    prompt_id = await submit(workflow)
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
                        job.status = "failed"
                        job.error = result.get("reason") or "ComfyUI reported an error"
                        job.finished_at = datetime.utcnow()
                        await db.commit()
                        logger.warning("job %s (%s) failed: %s",
                                       job_id, job.kind, job.error)
                except Exception as e:
                    job.status = "failed"
                    job.error = str(e)
                    job.finished_at = datetime.utcnow()
                    await db.commit()
                    logger.exception("job %s (%s) raised", job_id, job.kind)
        finally:
            self._inflight.discard(job_id)

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
