"""Background jobs with progress, logs, pause/stop and a broadcast event bus."""
from __future__ import annotations

import itertools
import queue
import threading
import time
import traceback
import uuid
from typing import Any, Callable


class EventBus:
    """Fan-out of JSON-able events to every connected UI (SSE subscribers)."""

    def __init__(self) -> None:
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, kind: str, data: dict) -> None:
        event = {"type": kind, "data": data, "at": time.time()}
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass


class JobCancelled(Exception):
    pass


class Job:
    _counter = itertools.count(1)

    def __init__(self, manager: "JobManager", kind: str, title: str, meta: dict | None = None):
        self.manager = manager
        self.id = f"{kind}-{next(self._counter)}-{uuid.uuid4().hex[:6]}"
        self.kind = kind
        self.title = title
        self.meta = meta or {}
        self.state = "queued"          # queued|running|paused|waiting|done|failed|stopped
        self.done = 0
        self.total = 0
        self.message = ""
        self.logs: list[dict] = []
        self.result: Any = None
        self.error = ""
        self.action: dict | None = None  # e.g. {"type": "login", "url": ...}
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.signals: dict[str, threading.Event] = {}
        self._last_progress_emit = 0.0
        self.version = 0

    # -- reporting -------------------------------------------------------
    def snapshot(self, with_logs: bool = False) -> dict:
        data = {
            "id": self.id, "kind": self.kind, "title": self.title, "meta": self.meta,
            "state": self.state, "done": self.done, "total": self.total,
            "message": self.message, "error": self.error, "action": self.action,
            "result": self.result, "started_at": self.started_at, "finished_at": self.finished_at,
            "version": self.version,
        }
        if with_logs:
            data["logs"] = self.logs[-500:]
        return data

    def emit(self, force: bool = True) -> None:
        now = time.monotonic()
        if not force and now - self._last_progress_emit < 0.15:
            return
        self._last_progress_emit = now
        self.version += 1
        self.manager.bus.publish("job", self.snapshot())

    def log(self, level: str, text: str) -> None:
        entry = {"level": level, "text": text, "at": time.time()}
        self.logs.append(entry)
        if len(self.logs) > 3000:
            self.logs = self.logs[-2000:]
        self.manager.bus.publish("log", {"job": self.id, **entry})

    def progress(self, done: int, total: int | None = None, message: str | None = None) -> None:
        self.version += 1
        self.done = done
        if total is not None:
            self.total = total
        if message is not None:
            self.message = message
        self.emit(force=done == self.total)

    def item(self, payload: dict) -> None:
        self.manager.bus.publish("item", {"job": self.id, **payload})

    def set_state(self, state: str, message: str | None = None) -> None:
        self.state = state
        if message is not None:
            self.message = message
        self.emit()

    def request_action(self, action: dict) -> None:
        self.action = action
        self.set_state("waiting")

    def clear_action(self) -> None:
        self.action = None
        self.set_state("running")

    def signal(self, name: str) -> threading.Event:
        return self.signals.setdefault(name, threading.Event())

    # -- cooperative control ----------------------------------------------
    def check(self) -> None:
        """Raise when stopped; block while paused."""
        if self.stop_event.is_set():
            raise JobCancelled()
        if self.pause_event.is_set():
            previous = self.state
            self.set_state("paused")
            while self.pause_event.is_set() and not self.stop_event.is_set():
                time.sleep(0.2)
            if self.stop_event.is_set():
                raise JobCancelled()
            self.set_state("running" if previous == "paused" else previous)

    def sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            self.check()
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

    @property
    def stopped(self) -> bool:
        return self.stop_event.is_set()


class JobManager:
    def __init__(self, bus: EventBus | None = None):
        self.bus = bus or EventBus()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, title: str, target: Callable[[Job], Any], meta: dict | None = None) -> Job:
        job = Job(self, kind, title, meta)
        with self._lock:
            self._jobs[job.id] = job
            # keep memory bounded
            finished = [j for j in self._jobs.values() if j.finished_at]
            for old in sorted(finished, key=lambda j: j.finished_at or 0)[:-30]:
                self._jobs.pop(old.id, None)

        def runner() -> None:
            job.set_state("running")
            try:
                job.result = target(job)
                job.state = "stopped" if job.stopped else "done"
            except JobCancelled:
                job.state = "stopped"
                job.log("warn", "عملیات متوقف شد.")
            except Exception as exc:  # noqa: BLE001
                job.state = "failed"
                job.error = str(exc) or type(exc).__name__
                job.log("error", job.error)
                job.meta["trace"] = traceback.format_exc()[-4000:]
            finally:
                job.action = None
                job.finished_at = time.time()
                job.emit()

        threading.Thread(target=runner, name=f"job-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            jobs = list(self._jobs.values())
        return [j.snapshot() for j in sorted(jobs, key=lambda j: j.started_at, reverse=True)]

    def active(self, kind: str | None = None) -> list[Job]:
        return [j for j in self._jobs.values() if not j.finished_at and (kind is None or j.kind == kind)]

    def control(self, job_id: str, action: str) -> bool:
        job = self.get(job_id)
        if not job:
            return False
        if action == "stop":
            job.stop_event.set()
            job.pause_event.clear()
            for ev in job.signals.values():
                ev.set()
        elif action == "pause":
            job.pause_event.set()
        elif action == "resume":
            job.pause_event.clear()
        else:
            job.signal(action).set()
        return True
