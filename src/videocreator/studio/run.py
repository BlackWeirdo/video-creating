"""One run of a Studio session: the agent calls, the script check and the scene render with one fix."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from videocreator.ai.base import AIProvider
from videocreator.config import Settings
from videocreator.db import get_conn
from videocreator.engines.mpt_client import MPTClient
from videocreator.paths import AppPaths
from videocreator.pipeline.plan_prompts import check_plan_facts
from videocreator.studio.audio import synthesize_scene_voices, voice_fit_problems
from videocreator.studio.checks import check_studio_project_dir, scan_scene_contract
from videocreator.studio.claude_agent import CodeGenerator
from videocreator.studio.export import update_session
from videocreator.studio.plan import load_plan, validate_plan, video_plan_json, write_plan_ts
from videocreator.studio.prompts import build_plan_prompt, build_revise_prompt, build_scene_prompt
from videocreator.studio.remotion import StudioRenderError, render_session, scaffold_session


@dataclass
class CheckedScript:
    """`plan.json` after the app's checks; `clips` is None when no voice was synthesized."""

    title: str
    scenes: list[dict[str, Any]]
    clips: list[Path | None] | None
    problems: list[str]


@dataclass
class StudioRun:
    paths: AppPaths
    settings: Settings
    session_id: int
    video_id: int
    options: dict[str, Any]
    user_prompt: str
    revision: str | None
    brief: dict[str, Any]
    footage_files: dict[str, Path]
    generate: CodeGenerator | None
    mpt_client: MPTClient | None
    checker_provider: AIProvider | None
    session_ref: str
    cost_usd: float = 0.0

    @property
    def session_dir(self) -> Path:
        return self.paths.media_dir / "studio" / str(self.session_id)

    @property
    def scene_file(self) -> Path:
        return self.session_dir / "src" / "Scene.tsx"

    @property
    def from_template(self) -> bool:
        return bool(self.options.get("template_id"))

    @property
    def voice_lang(self) -> str:
        return str(self.options.get("voice_lang") or "none")

    def scaffold(self) -> None:
        """(Re)writes the app-owned files of the session project."""
        safe_zone = (self.settings.safe_zone.top, self.settings.safe_zone.bottom, self.settings.safe_zone.right)
        scaffold_session(self.session_dir, footage_files=self.footage_files, brief=self.brief, safe_zone=safe_zone)

    def call_agent(self, prompt: str, attempt: int) -> None:
        assert self.generate is not None
        ref, cost = self.generate(self.session_dir, prompt, attempt, self.session_ref or None)
        self.session_ref = ref or self.session_ref
        self.cost_usd += cost
        update_session(self.paths.db_file, self.session_id, session_ref=self.session_ref or None)

    def checked_script(self) -> CheckedScript:
        """Loads and checks plan.json, including that each voice line fits its scene."""
        plan, problems = load_plan(self.session_dir)
        if plan is None:
            return CheckedScript("", [], None, problems)
        scenes, problems = validate_plan(plan, self.brief)
        clips: list[Path | None] | None = None
        if not problems and self.voice_lang in ("vi", "en"):
            clips = synthesize_scene_voices(
                self.paths, self.session_dir, scenes, self.voice_lang, mpt_client=self.mpt_client
            )
            if clips is not None:
                problems = voice_fit_problems(scenes, clips)
        title = str(plan.get("title") or "").strip() or f"Studio #{self.session_id}"
        return CheckedScript(title, scenes, clips, problems)

    def save_video_plan(self, script: CheckedScript, claims: list[str]) -> dict[str, Any]:
        plan_json = video_plan_json(
            script.title, script.scenes, voice_lang=self.voice_lang, unverified_claims=claims
        )
        with get_conn(self.paths.db_file) as conn:
            conn.execute(
                "UPDATE videos SET plan_json = ?, product_ids_json = ?, voice_lang = ? WHERE id = ?",
                (
                    json.dumps(plan_json, ensure_ascii=False),
                    json.dumps(plan_json["product_ids"]),
                    self.voice_lang,
                    self.video_id,
                ),
            )
        return plan_json

    def write_script(self) -> tuple[CheckedScript, dict[str, Any]]:
        """Stage 1: the agent writes the script (one fix allowed); it is fact-checked and saved."""
        problems: list[str] = []
        for attempt in (1, 2):
            if self.scene_file.exists() and self.revision:
                prompt = build_revise_prompt(self.user_prompt, self.revision, problems, self.settings)
            else:
                prompt = build_plan_prompt(self.user_prompt, self.revision, problems)
            self.call_agent(prompt, attempt)
            script = self.checked_script()
            problems = script.problems
            if not problems:
                break
        if problems:
            raise ValueError(f"Kịch bản Studio không qua kiểm tra sau một lần sửa: {'; '.join(problems)[:500]}")

        claims = check_plan_facts(
            self.paths,
            {"shots": [{"text": s["text"]} for s in script.scenes], "captions": {}},
            self.brief["products"],
            checker_provider=self.checker_provider,
        )
        return script, self.save_video_plan(script, claims)

    def _scene_problems(self) -> list[str]:
        """`BR-PRD-02` scan of the session project and of the scene code."""
        problems = check_studio_project_dir(
            self.session_dir / "src", allowed_video_filenames=set(self.footage_files)
        )
        if not self.scene_file.exists():
            return problems + ["src/Scene.tsx chưa được tạo"]
        return problems + scan_scene_contract(self.scene_file.read_text(encoding="utf-8", errors="replace"))

    def render_scene(self, script: CheckedScript, raw_out: Path) -> None:
        """Stage 2: scene code -> scan -> Remotion render, with one fix by the agent (`FR-STD-07`)."""
        problems: list[str] = []
        for attempt in (1, 2):
            if attempt == 2 or not self.scene_file.exists():
                if self.from_template or self.generate is None:
                    break
                self.call_agent(build_scene_prompt(self.user_prompt, problems, self.settings), attempt)
            # App-owned files are rewritten before every render, whatever the agent did to them.
            self.scaffold()
            write_plan_ts(self.session_dir, script.title, script.scenes)
            problems = self._scene_problems()
            if not problems:
                try:
                    render_session(self.session_dir, raw_out)
                except StudioRenderError as exc:
                    problems = [f"remotion render lỗi: {exc}"]
            if not problems:
                return
        if problems:
            raise ValueError(f"Studio không qua kiểm tra sau một lần sửa: {'; '.join(problems)[:600]}")
