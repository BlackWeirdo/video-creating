"""Real SQLite tests for subscription-first routing, quota cooldown, waiting_quota jobs, and planner validation (Phase 04 & 18)."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from videocreator.ai.base import ProviderQuotaExhausted, RouteKind, T
from videocreator.ai.quota import clear_provider_rest, is_provider_resting, mark_provider_resting
from videocreator.ai.router import RoutedProvider
from videocreator.config import load_settings, save_settings
from videocreator.db import migrate
from videocreator.jobs import (
    JobRegistry,
    JobWorker,
    enqueue_job,
    get_job,
    wake_expired_quota_jobs,
)
from videocreator.paths import get_paths
from videocreator.pipeline.planner import (
    PlannedShot,
    PlatformCaption,
    PlatformCaptions,
    VideoPlanItem,
    jaccard_similarity,
    validate_and_normalize_plan,
)


class SimpleReply(BaseModel):
    answer: str


class DeterministicProvider:
    """In-process provider implementation for testing router order & SQLite state transitions."""

    def __init__(
        self,
        name: str,
        route_kind: RouteKind,
        reply_text: str,
        *,
        quota_exhaust_on_first: bool = False,
    ) -> None:
        self.name = name
        self.route_kind: RouteKind = route_kind
        self.reply_text = reply_text
        self.quota_exhaust_on_first = quota_exhaust_on_first
        self.calls = 0

    def describe_video(
        self,
        video: Path,
        prompt: str,
        schema: type[T],
        *,
        thumbnails: list[Path] | None = None,
    ) -> T:
        return self.generate_json(prompt, schema)

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        self.calls += 1
        if self.quota_exhaust_on_first and self.calls == 1:
            # 60 s, not 1 s: the test asserts the provider is still resting a moment later, which
            # failed under load. Tests clear the rest explicitly with clear_provider_rest().
            raise ProviderQuotaExhausted(self.name, "5-hour limit reached", retry_after_s=60)
        return schema.model_validate({"answer": f"{self.reply_text}:{self.calls}"})


@pytest.mark.local
def test_router_respects_resting_state_and_dynamic_route_order(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    cfg = load_settings(paths.config_file)
    cfg.ai.policy.api_fallback = "auto"
    cfg.ai.routes.writer = ["claude_cli", "claude_api"]
    save_settings(paths.config_file, cfg)

    p_sub = DeterministicProvider("claude_cli", "subscription", "from_sub")
    p_api = DeterministicProvider("claude_api", "api", "from_api")
    overrides = {"claude_cli": p_sub, "claude_api": p_api}

    router = RoutedProvider(paths, "writer", provider_overrides=overrides)

    # 1. Both healthy -> subscription first
    res1 = router.generate_json("hello", SimpleReply)
    assert res1.answer == "from_sub:1"
    assert router.last_used_provider == "claude_cli"

    # 2. Mark claude_cli resting in SQLite -> falls back to claude_api under auto
    mark_provider_resting(paths.db_file, "claude_cli", duration_s=600, error_msg="quota limit")
    res2 = router.generate_json("hello", SimpleReply)
    assert res2.answer == "from_api:1"
    assert router.last_used_provider == "claude_api"

    # 3. Clear resting and swap order in config.toml -> takes effect immediately without code changes
    clear_provider_rest(paths.db_file, "claude_cli")
    cfg.ai.routes.writer = ["claude_api", "claude_cli"]
    save_settings(paths.config_file, cfg)

    res3 = router.generate_json("hello", SimpleReply)
    assert res3.answer == "from_api:2"
    assert router.last_used_provider == "claude_api"


@pytest.mark.local
def test_policy_never_puts_job_in_waiting_quota_until_recovery(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    cfg = load_settings(paths.config_file)
    cfg.ai.policy.api_fallback = "never"
    cfg.ai.routes.writer = ["claude_cli", "claude_api"]
    save_settings(paths.config_file, cfg)

    p_sub = DeterministicProvider(
        "claude_cli", "subscription", "sub_ok", quota_exhaust_on_first=True
    )
    p_api = DeterministicProvider("claude_api", "api", "api_should_not_run")
    overrides = {"claude_cli": p_sub, "claude_api": p_api}
    router = RoutedProvider(paths, "writer", provider_overrides=overrides)

    reg = JobRegistry()
    reg.register("plan", lambda ref_id: router.generate_json("make plan", SimpleReply).answer)
    worker = JobWorker(paths.db_file, registry=reg)

    jid = enqueue_job(paths.db_file, "plan", ref_id=1)

    # First run: claude_cli raises ProviderQuotaExhausted(retry_after_s=60), policy='never' skips claude_api
    # -> job transitions to waiting_quota
    assert worker.run_next_once() is True
    j_wait = get_job(paths.db_file, jid)
    assert j_wait is not None
    assert j_wait["status"] == "waiting_quota"
    assert p_api.calls == 0  # API never called!
    resting, _ = is_provider_resting(paths.db_file, "claude_cli")
    assert resting is True

    # Simulate cooldown expiry in SQLite and wake waiting jobs
    clear_provider_rest(paths.db_file, "claude_cli")
    woken = wake_expired_quota_jobs(paths.db_file)
    assert woken == 1

    assert worker.run_next_once() is True
    j_done = get_job(paths.db_file, jid)
    assert j_done is not None
    assert j_done["status"] == "done"
    assert j_done["log_tail"] == "sub_ok:2"
    assert p_api.calls == 0


@pytest.mark.local
def test_planner_validation_product_rules_and_jaccard() -> None:
    assert jaccard_similarity({1, 2, 3}, {1, 2, 3}) == 1.0
    assert jaccard_similarity({1, 2, 3, 4}, {1, 2, 3, 5}) == pytest.approx(3 / 5)

    shot_map = {
        10: {"id": 10, "start_s": 0.0, "end_s": 4.0, "product_ids": [1]},
        11: {"id": 11, "start_s": 4.0, "end_s": 8.5, "product_ids": [1]},
        12: {"id": 12, "start_s": 8.5, "end_s": 13.0, "product_ids": [2]},
    }
    product_map = {
        1: {"id": 1, "name": "Nhẫn Xúc Xắc", "material": "Bạc S925", "facts": {}},
        2: {"id": 2, "name": "Vòng Tay Rồng", "material": "Bạc S925", "facts": {}},
    }
    dummy_caps = PlatformCaptions(
        facebook=PlatformCaption(text="FB", hashtags=["bac", "thucong"]),
        instagram=PlatformCaption(text="IG", hashtags=["bac"]),
        threads=PlatformCaption(text="TH", hashtags=["bac", "extra_dropped"]),
        tiktok=PlatformCaption(text="TT", hashtags=["bac"]),
    )

    # 1. Hallucinated shot_id=999 must be rejected (FR-PLN-03)
    bad_shot_plan = VideoPlanItem(
        formula="hook-first",
        title="Bad Shot",
        shots=[PlannedShot(shot_id=999, start_s=0.0, duration_s=3.0, text="Test")],
        captions=dummy_caps,
    )
    with pytest.raises(ValueError, match="FR-PLN-03"):
        validate_and_normalize_plan(
            bad_shot_plan,
            shot_map=shot_map,
            product_map=product_map,
            voice_lang="vi",
            caption_lang="vi",
            target_duration_s=10.0,
        )

    # 2. Mentioning Product 2 ("Vòng Tay Rồng") on Shot 10 (which only has Product 1) -> rejected (BR-PRD-05)
    mismatched_text_plan = VideoPlanItem(
        formula="hook-first",
        title="Mismatch",
        shots=[
            PlannedShot(shot_id=10, start_s=0.0, duration_s=3.5, text="Chiếc Vòng Tay Rồng chạm khắc"),
            PlannedShot(shot_id=11, start_s=4.0, duration_s=3.5, text="Hoàn thiện tỉ mỉ"),
        ],
        captions=dummy_caps,
    )
    with pytest.raises(ValueError, match="BR-PRD-05"):
        validate_and_normalize_plan(
            mismatched_text_plan,
            shot_map=shot_map,
            product_map=product_map,
            voice_lang="vi",
            caption_lang="vi",
            target_duration_s=10.0,
        )

    # 3. Valid plan normalizes shots and enforces Threads <= 1 hashtag limit
    valid_plan = VideoPlanItem(
        formula="hook-first",
        title="Nhẫn Xúc Xắc Thủ Công",
        shots=[
            PlannedShot(shot_id=10, start_s=0.0, duration_s=3.5, text="Cận cảnh Nhẫn Xúc Xắc"),
            PlannedShot(shot_id=11, start_s=4.0, duration_s=4.0, text="Ánh bạc S925 nguyên khối"),
        ],
        captions=dummy_caps,
    )
    norm = validate_and_normalize_plan(
        valid_plan,
        shot_map=shot_map,
        product_map=product_map,
        voice_lang="vi",
        caption_lang="vi",
        target_duration_s=8.0,
    )
    assert norm["product_ids"] == [1]
    assert norm["total_duration_s"] == 7.5
    assert norm["captions"]["threads"]["hashtags"] == ["#bac"]  # capped at 1 hashtag for Threads


@pytest.mark.local
def test_describe_planner_and_video_routes_end_to_end(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from videocreator.api.routes_products import create_product
    from videocreator.app import create_app
    from videocreator.db import get_conn
    from videocreator.pipeline.describe import ShotDescriptionItem, ShotDescriptionsResponse, run_describe_footage
    from videocreator.pipeline.planner import FactCheckResult, RemixPlansBatch, create_remix_plans

    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths

    pid = create_product(
        paths.db_file,
        name="Nhẫn Xúc Xắc",
        material="Bạc S925",
        facts={"stone": "Không đính đá", "craftsmanship": "Chạm khắc thủ công"},
    )
    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO footage (id, path, sha256, duration_s, width, height, orientation, product_ids_json, status)
            VALUES (1, 'footage/1.mp4', 'sha_ftg_1', 12.0, 1080, 1920, 'portrait', ?, 'analysed')
            """,
            (f"[{pid}]",),
        )
        for idx, (st, en) in enumerate([(0.0, 4.0), (4.0, 8.0), (8.0, 12.0)], start=1):
            conn.execute(
                """
                INSERT INTO shots (id, footage_id, idx, start_s, end_s, has_product, product_ids_json, thumb_path)
                VALUES (?, 1, ?, ?, ?, 1, ?, ?)
                """,
                (idx, idx, st, en, f"[{pid}]", f"thumbs/shot_1_{idx:03d}.jpg"),
            )

    class EndToEndProvider:
        name = "claude_cli"
        route_kind: RouteKind = "subscription"

        def describe_video(self, video: Path, prompt: str, schema: type[T], *, thumbnails=None) -> T:
            return schema.model_validate(
                ShotDescriptionsResponse(
                    shots=[
                        ShotDescriptionItem(idx=1, description="Tay thợ dũa nhẫn bạc", tags=["chế tác", "tay thợ"], has_product=True, quality=4),
                        ShotDescriptionItem(idx=2, description="Cận cảnh mặt nhẫn xúc xắc", tags=["cận cảnh", "nhẫn bạc"], has_product=True, quality=5),
                        ShotDescriptionItem(idx=3, description="Đeo nhẫn trên tay", tags=["đeo tay", "ánh sáng"], has_product=True, quality=4),
                    ]
                ).model_dump()
            )

        def generate_json(self, prompt: str, schema: type[T]) -> T:
            if schema is FactCheckResult:
                return schema.model_validate({"unverified_claims": ["Đính kim cương tự nhiên 1 carat"]})
            caps = PlatformCaptions(
                facebook=PlatformCaption(text="Nhẫn Xúc Xắc bạc S925 thủ công", hashtags=["bac925", "thucong", "nhanbac"]),
                instagram=PlatformCaption(text="Chi tiết chạm khắc thủ công", hashtags=["bac925", "jewelry", "silver"]),
                threads=PlatformCaption(text="Một chiếc nhẫn xúc xắc bạc S925 vừa hoàn thiện tại xưởng.", hashtags=["bac925"]),
                tiktok=PlatformCaption(text="Quy trình hoàn thiện nhẫn bạc thủ công", hashtags=["bac925", "xuhuong", "handmade"]),
            )
            return schema.model_validate(
                RemixPlansBatch(
                    plans=[
                        VideoPlanItem(
                            formula="hook-first",
                            title="Nhẫn Xúc Xắc Cận Cảnh",
                            shots=[
                                PlannedShot(shot_id=2, start_s=4.0, duration_s=3.5, text="Cận cảnh Nhẫn Xúc Xắc bạc S925"),
                                PlannedShot(shot_id=1, start_s=0.0, duration_s=3.5, text="Chạm khắc thủ công từng đường nét"),
                            ],
                            captions=caps,
                        ),
                        VideoPlanItem(
                            formula="craft-process",
                            title="Từ Xưởng Tới Tay",
                            shots=[
                                PlannedShot(shot_id=1, start_s=0.0, duration_s=3.5, text="Bắt đầu từ phôi bạc S925"),
                                PlannedShot(shot_id=3, start_s=8.0, duration_s=3.5, text="Đính kim cương tự nhiên 1 carat"),
                            ],
                            captions=caps,
                        ),
                    ]
                ).model_dump()
            )

    prov = EndToEndProvider()
    desc_out = run_describe_footage(paths, 1, provider=prov)
    assert "Described 3/3 shots" in desc_out

    vids = create_remix_plans(
        paths,
        1,
        count=2,
        voice_lang="vi",
        caption_lang="vi",
        target_duration_s=8.0,
        writer_provider=prov,
        checker_provider=prov,
    )
    assert len(vids) == 2

    with TestClient(app) as client:
        r_list = client.get("/videos")
        assert r_list.status_code == 200
        assert "Nhẫn Xúc Xắc Cận Cảnh" in r_list.text
        assert "1 câu cần rà soát" in r_list.text

        r_detail = client.get(f"/videos/{vids[0]}")
        assert r_detail.status_code == 200
        assert "Đính kim cương tự nhiên 1 carat" in r_detail.text

        r_update = client.post(
            f"/videos/{vids[0]}/update-plan",
            data={
                "title": "Nhẫn Xúc Xắc Đã Duyệt Lời",
                "shot_text_0": "Cận cảnh mặt nhẫn bạc S925",
                "shot_text_1": "Hoàn thiện thủ công tại xưởng",
                "caption_facebook_text": "Nhẫn bạc S925 chạm khắc thủ công",
                "caption_facebook_hashtags": "#bac925 #thucong",
                "clear_unverified": "true",
            },
            follow_redirects=True,
        )
        assert r_update.status_code == 200
        assert "Nhẫn Xúc Xắc Đã Duyệt Lời" in r_update.text
        assert "Khớp facts_json" in r_update.text

        r_ai = client.get("/ai-routes")
        assert r_ai.status_code == 200
        assert "claude_cli" in r_ai.text
