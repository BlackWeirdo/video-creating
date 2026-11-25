"""Centralized 8 GB RAM safety guard (`gc.collect()`) and studio job execution wrapper."""
from __future__ import annotations

import gc
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from videocreator.job_store import report_active_job_progress


@contextmanager
def compute_job_scope(*, start_step: str = "") -> Iterator[None]:
    """Wraps heavy CPU/FFmpeg/ONNX job execution to guarantee `gc.collect()` on exit."""
    if start_step:
        report_active_job_progress(0.05, start_step)
    try:
        yield
    finally:
        gc.collect()


def run_studio_project_job(
    render_fn: Callable[..., dict[str, Any]],
    *args: Any,
    default_status: str = "completed",
    **kwargs: Any,
) -> str:
    """Runs a studio render/extract function inside `compute_job_scope` and returns its status string."""
    with compute_job_scope():
        result = render_fn(*args, **kwargs)
    return str(result.get("status") or default_status)
