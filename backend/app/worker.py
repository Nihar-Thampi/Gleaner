"""The scheduler and run queue.

By default it runs on a background thread inside the API process (its own asyncio loop,
so crawling never blocks API requests). For larger deployments set RUN_WORKER=false on the
API and run this module as a separate process: `python -m app.worker`.
"""
import asyncio
import logging
import threading

from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import Run, RunStatus
from app.scraper.engine import execute_run
from app.services.runs import fail_interrupted_runs, queue_due_scrapers

logger = logging.getLogger(__name__)

TICK_SECONDS = 5


class Worker:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._stop = threading.Event()
        self._running: dict[str, asyncio.Task] = {}
        self._thread: threading.Thread | None = None

    # ---- lifecycle ----

    def start_in_thread(self) -> None:
        self._thread = threading.Thread(target=self.run_forever, name="gleaner-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.wake()

    def wake(self) -> None:
        """Called from API threads after queueing a run, so it starts right away."""
        if self.loop and self._wake:
            self.loop.call_soon_threadsafe(self._wake.set)

    def run_forever(self) -> None:
        asyncio.run(self._main())

    # ---- loop ----

    async def _main(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        with SessionLocal() as db:
            if n := fail_interrupted_runs(db):
                logger.info("Marked %d interrupted run(s) as failed", n)
        logger.info("Worker started (max %d concurrent runs)", get_settings().max_concurrent_runs)
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:  # noqa: BLE001 - keep the loop alive
                logger.exception("Worker tick failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=TICK_SECONDS)
            except TimeoutError:
                pass
            self._wake.clear()
        for task in self._running.values():
            task.cancel()

    def _tick(self) -> None:
        with SessionLocal() as db:
            queue_due_scrapers(db)
            slots = get_settings().max_concurrent_runs - len(self._running)
            if slots <= 0:
                return
            queued = db.scalars(
                select(Run.id).where(Run.status == RunStatus.queued, Run.id.not_in(list(self._running) or [""]))
                .order_by(Run.created_at).limit(slots)
            ).all()
        for run_id in queued:
            task = asyncio.create_task(execute_run(run_id))
            self._running[run_id] = task
            task.add_done_callback(lambda _t, rid=run_id: self._done(rid))

    def _done(self, run_id: str) -> None:
        self._running.pop(run_id, None)
        if self._wake:
            self._wake.set()  # a slot freed up


worker = Worker()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        pass
