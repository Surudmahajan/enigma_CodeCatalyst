"""Background job execution.

Expensive work (match recalculation, embeddings, document extraction,
notification fan-out) is enqueued here so it does not block the request.

* ``thread`` mode: a bounded in-process worker pool (default for the MVP).
* ``eager`` mode: jobs run inline; used by tests for determinism.

Jobs receive IDs, never ORM objects, and open their own DB session, so the
same job functions can move to a Redis-backed queue (RQ/Arq/Celery) later
without changing call sites.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("symbio.jobs")

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="symbio-job")
    return _executor


def _run(job: Callable[..., Any], args: tuple, kwargs: dict) -> None:
    try:
        job(*args, **kwargs)
    except Exception:  # a failed job must never crash the worker pool
        logger.exception("Background job %s failed", getattr(job, "__name__", job))


def enqueue(job: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    if get_settings().jobs_mode == "eager":
        _run(job, args, kwargs)
    else:
        _get_executor().submit(_run, job, args, kwargs)


def shutdown() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None
