"""Bound actual running work, carrying one deadline through nested operations."""

from __future__ import annotations

import contextvars
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from typing import TypeVar

T = TypeVar("T")
_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar("work_deadline", default=None)


class WorkTimeoutError(TimeoutError):
    """The entire operation exhausted its wall-clock budget."""


class WorkCapacityError(RuntimeError):
    """All execution slots are busy, including timed-out work still running."""


def remaining_timeout(cap: float | None = None) -> float | None:
    deadline = _deadline.get()
    if deadline is None:
        return cap
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise WorkTimeoutError("Operation exceeded its time budget.")
    return remaining if cap is None else min(cap, remaining)


@contextmanager
def deadline_scope(timeout: float) -> Iterator[None]:
    deadline = time.monotonic() + max(0.001, timeout)
    inherited = _deadline.get()
    token = _deadline.set(min(deadline, inherited) if inherited is not None else deadline)
    try:
        remaining_timeout()
        yield
    finally:
        _deadline.reset(token)


class BoundedWorkPool:
    """Reject excess work without queueing; capacity belongs to the running worker.

    A caller timing out or disconnecting does not release the worker's slot. Only
    termination of the callable does that. Late results remain private to its Future.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._lock = threading.Lock()
        self._active = 0

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    def run(self, fn: Callable[[], T], *, timeout: float, limit: int) -> T:
        with deadline_scope(timeout):
            context = contextvars.copy_context()
            with self._lock:
                if self._active >= max(1, limit):
                    raise WorkCapacityError("Processing capacity is full.")
                self._active += 1
            future: Future[T] = Future()

            def call() -> T:
                remaining_timeout()
                result = fn()
                remaining_timeout()
                return result

            def execute() -> None:
                try:
                    result = context.run(call)
                    future.set_result(result)
                except BaseException as exc:
                    future.set_exception(exc)
                finally:
                    with self._lock:
                        self._active -= 1

            try:
                threading.Thread(target=execute, name=self.name, daemon=True).start()
            except BaseException:
                with self._lock:
                    self._active -= 1
                raise
            try:
                return future.result(timeout=remaining_timeout())
            except TimeoutError as exc:
                raise WorkTimeoutError("Operation exceeded its time budget.") from exc
