"""Shared Jinja2 template environment: built once per templates folder, not once per request."""
from __future__ import annotations

from functools import lru_cache

from fastapi.templating import Jinja2Templates

from videocreator.paths import AppPaths


@lru_cache(maxsize=4)
def _templates_for(directory: str) -> Jinja2Templates:
    return Jinja2Templates(directory=directory)


def get_templates(paths: AppPaths) -> Jinja2Templates:
    """The template environment of `paths.templates_dir` (compiled templates stay cached across requests)."""
    return _templates_for(str(paths.templates_dir))
