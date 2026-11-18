"""End-to-end real tests for Phases 1–6: Outlier Trend Ranking, Actionable Blueprints,
Beat-Synced Audio, FFmpeg Enhanced ASS Presets, Multi-Provider Studio (Remotion) AI Editor,
and Vision `trend_alignment` Quality Scoring + Self-Revision.

Zero mocks (per CLAUDE.md): real SQLite, real FFmpeg, real Remotion, and deterministic
provider objects implementing the `AIProvider` protocol.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from videocreator.ai.budget import record_usage
from videocreator.api.routes_assets import import_audio_asset
from videocreator.app import create_app
from videocreator.config import load_settings, save_settings
from videocreator.db import get_conn, migrate, query_all, query_one
from videocreator.paths import get_paths
from videocreator.pipeline.audio_beats import analyse_music_beats, snap_shots_to_beats
from videocreator.pipeline.ffmpeg import run_ffmpeg, validate_filtergraph_allowed
from videocreator.pipeline.footage_import import import_footage_file
from videocreator.pipeline.plan_schema import FactCheckResult, VideoPlanItem
from videocreator.pipeline.plan_validate import validate_and_normalize_plan
from videocreator.pipeline.planner import create_remix_plans
from videocreator.pipeline.preflight import inspect_master_streams
from videocreator.pipeline.quality_score import TrendVideoQualityScore, overall_from, weakest_hint
from videocreator.pipeline.render import render_video
from videocreator.pipeline.render_inputs import build_segment_filter_args, pick_music_asset_record
from videocreator.pipeline.subtitles import SubtitleEvent, build_ass
from videocreator.products import create_product
from videocreator.secrets_store import SecretsStore
from videocreator.studio.agent import run_studio_job
from videocreator.studio.api_agent import (
    StudioPlanGenSchema,
    StudioReviseGenSchema,
    StudioSceneGenSchema,
    can_start_studio_editor,
    make_studio_generator,
)
from videocreator.studio.checks import scan_scene_contract, scan_tsx_for_product_violations
from videocreator.studio.remotion_files import LIB_TSX
from videocreator.trends.analyse import TrendAnalysisSchema, analyse_trend_item
from videocreator.trends.apify_mappers import map_facebook_reel, map_instagram, map_tiktok
from videocreator.trends.base import TrendItem
from videocreator.trends.rea_reference import detect_rea_lang
from videocreator.trends.scan import upsert_trend_item
from videocreator.trends.suggest import (
    SuggestionsBatchSchema,
    make_suggestions,
    select_suggestion_candidates,
    winning_formulas_summary,
)
from videocreator.trends.suggestion_actions import accept_suggestion

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
CLIP_PORTRAIT = SAMPLES_DIR / "clip1_6s.mp4"
CLIP_LANDSCAPE = SAMPLES_DIR / "clip_landscape_5s.mp4"


@pytest.mark.local
def test_outlier_scoring_apify_mappers_and_per_source_balanced_selection(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    # 1. Language auto-detection for rea-video
    assert detect_rea_lang("Chế tác nhẫn bạc thủ công tại xưởng Hà Nội") == "vi"
    assert detect_rea_lang("Handcrafted sterling silver wax carving") == "en"

    # 2. Apify mappers preserve saves, shares, likes, and author_followers
    tt = map_tiktok(
        {
            "id": "tt_99",
            "webVideoUrl": "https://www.tiktok.com/@smallmaker/video/99",
            "createTimeISO": "2026-11-17T08:00:00Z",
            "playCount": 45000,
            "diggCount": 3200,
            "commentCount": 180,
            "shareCount": 620,
            "collectCount": 910,
            "authorMeta": {"name": "smallmaker", "fans": 2400},
            "videoMeta": {"duration": 9},
        }
    )
    assert tt is not None
    assert tt.metrics["saves"] == 910
    assert tt.metrics["shares"] == 620
    assert tt.metrics["author_followers"] == 2400

    ig = map_instagram(
        {
            "type": "Video",
            "shortCode": "IG_99",
            "url": "https://www.instagram.com/reel/IG_99/",
            "timestamp": "2026-11-17T08:00:00Z",
            "videoPlayCount": 30000,
            "likesCount": 2100,
            "commentsCount": 90,
            "sharesCount": 400,
            "savesCount": 550,
            "ownerUsername": "silverbench",
            "ownerFollowersCount": 3100,
            "videoDuration": 8.4,
        },
        source="ig_hashtag",
    )
    assert ig is not None
    assert ig.metrics["saves"] == 550 and ig.metrics["author_followers"] == 3100

    fb = map_facebook_reel(
        {
            "shareable_url": "https://www.facebook.com/reel/123456789",
            "time": "2026-11-17T08:00:00Z",
            "playCount": 28000,
            "likesCount": 900,
            "commentsCount": 75,
            "sharesCount": 310,
            "video": {"playable_duration_in_ms": 11500},
            "video_owner": {"name": "Silver Craft VN", "followers_count": 4200},
        }
    )
    assert fb is not None
    assert fb.metrics["likes"] == 900 and fb.metrics["shares"] == 310
    assert fb.metrics["author_followers"] == 4200

    # 3. Channel historical median velocity + small-account viral breakout multiplier
    now_dt = datetime(2026, 11, 18, 8, 0, 0, tzinfo=timezone.utc)
    pub_dt = now_dt - timedelta(hours=6)
    for idx in range(3):
        upsert_trend_item(
            paths.db_file,
            TrendItem(
                source="tiktok",
                external_id=f"hist_{idx}",
                url=f"https://tiktok.com/@indie/video/{idx}",
                author="indie_silver",
                caption="Bản thường ngày",
                published_at=pub_dt,
                metrics={"views": 900, "likes": 35, "comments": 2, "shares": 1, "saves": 2, "author_followers": 1800},
            ),
            now_dt=now_dt,
        )

    breakout_id = upsert_trend_item(
        paths.db_file,
        TrendItem(
            source="tiktok",
            external_id="breakout_1",
            url="https://tiktok.com/@indie/video/999",
            author="indie_silver",
            caption="Bản bùng nổ",
            published_at=pub_dt,
            metrics={"views": 25000, "likes": 1800, "comments": 120, "shares": 450, "saves": 600, "author_followers": 1800},
        ),
        now_dt=now_dt,
    )
    big_flat_id = upsert_trend_item(
        paths.db_file,
        TrendItem(
            source="tiktok",
            external_id="big_flat_1",
            url="https://tiktok.com/@mega/video/1",
            author="mega_brand",
            caption="Bản đều đều kênh lớn",
            published_at=pub_dt,
            metrics={"views": 25000, "likes": 1800, "comments": 120, "shares": 10, "saves": 5, "author_followers": 900000},
        ),
        now_dt=now_dt,
    )
    b_row = query_one(paths.db_file, "SELECT score, metrics_json FROM trend_items WHERE id = ?", (breakout_id,))
    m_row = query_one(paths.db_file, "SELECT score FROM trend_items WHERE id = ?", (big_flat_id,))
    assert b_row is not None and m_row is not None
    b_metrics = json.loads(b_row["metrics_json"])
    assert float(b_metrics.get("outlier_mult", 1.0)) >= 1.5
    assert float(b_row["score"]) > float(m_row["score"]) * 1.8

    # 4. Per-source balanced selection: high-scoring ad_library rows cannot crowd out TikTok/YouTube
    bp_json = json.dumps({"hook": "Mở đầu", "analysis_mode": "video"}, ensure_ascii=False)
    meta_only_json = json.dumps({"hook": "Chỉ caption", "analysis_mode": "metadata_only"}, ensure_ascii=False)
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM trend_items")
        for i in range(3):
            conn.execute(
                "INSERT INTO trend_items (source, external_id, url, author, published_at, score, analysis_json) "
                "VALUES ('ad_library', ?, 'https://fb.com/ads', 'AdBrand', '2026-11-17T00:00:00Z', ?, ?)",
                (f"ad_{i}", 300.0 - i, bp_json),
            )
        conn.execute(
            "INSERT INTO trend_items (source, external_id, url, author, published_at, score, analysis_json) "
            "VALUES ('tiktok', 'tt_top', 'https://tiktok.com/1', 'TT', '2026-11-17T00:00:00Z', 42.0, ?)",
            (bp_json,),
        )
        conn.execute(
            "INSERT INTO trend_items (source, external_id, url, author, published_at, score, analysis_json) "
            "VALUES ('youtube', 'yt_top', 'https://youtube.com/1', 'YT', '2026-11-17T00:00:00Z', 38.0, ?)",
            (bp_json,),
        )
        conn.execute(
            "INSERT INTO trend_items (source, external_id, url, author, published_at, score, analysis_json) "
            "VALUES ('instagram', 'ig_meta', 'https://instagram.com/1', 'IG', '2026-11-17T00:00:00Z', 500.0, ?)",
            (meta_only_json,),
        )

    cands = select_suggestion_candidates(paths.db_file)
    top3_sources = {c["source"] for c in cands[:3]}
    assert top3_sources == {"ad_library", "tiktok", "youtube"}
    # metadata_only item ranks behind all 5 real video-analysed items despite higher raw score
    assert cands[-1]["external_id"] == "ig_meta"


class _BlueprintProvider:
    name = "claude_api"
    route_kind = "api"

    def describe_video(self, video: Path, prompt: str, schema: type[TrendAnalysisSchema], *, thumbnails: list[Path] | None = None) -> TrendAnalysisSchema:
        return schema.model_validate(
            {
                "hook": "Cận cảnh giũa nhẫn bạc lấp lánh dưới đèn vàng",
                "structure": [
                    {"t": "0-2s", "duration_s": 2.0, "role": "hook", "what": "Giũa nhẫn bạc", "visual_tags": ["closeup", "craft"]},
                    {"t": "2-6s", "duration_s": 4.0, "role": "payoff", "what": "Đeo nhẫn hoàn thiện", "visual_tags": ["wearing"]},
                ],
                "cut_pace_s": 1.8,
                "text_style": "Chữ lớn nổi bật ở đầu",
                "music_mood": "Sôi động, bắt beat",
                "why_it_works": "Mở đầu có chuyển động tay thợ thật",
                "analysis_mode": "video",
                "reference_duration_s": 15.0,  # will be overwritten by probed actual duration (~6.0s)
                "audio_mode": "asmr_original",
                "hook_layout": "kinetic_words",
                "energy_level": "energetic",
            }
        )

    def generate_json(self, prompt: str, schema: type[TrendAnalysisSchema]) -> TrendAnalysisSchema:
        return schema.model_validate(
            {
                "hook": "Ý tưởng từ caption khi không tải được video",
                "structure": [],
                "cut_pace_s": 2.5,
                "text_style": "Gọn",
                "music_mood": "Ấm áp",
                "why_it_works": "Caption gợi tò mò",
                "analysis_mode": "video",  # must be forced to metadata_only by analyse_trend_item
            }
        )


@pytest.mark.local
def test_analyse_trend_item_blueprint_video_vs_metadata_only(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO trend_items (id, source, external_id, url, author, caption, published_at, score)
            VALUES
                (1, 'tiktok', 'v1', 'https://tiktok.com/1', 'ThoBac', 'Chế tác nhẫn bạc', '2026-11-17T00:00:00Z', 80.0),
                (2, 'facebook', 'v2', 'https://fb.com/reel/2', 'SilverPage', 'Caption only', '2026-11-17T00:00:00Z', 60.0)
            """
        )

    prov = _BlueprintProvider()
    bp_video = analyse_trend_item(
        paths,
        1,
        vision_provider=prov,
        writer_provider=prov,
        downloader_fn=lambda _u, dest: (dest.parent.mkdir(parents=True, exist_ok=True), shutil.copy2(CLIP_PORTRAIT, dest))[1] is not None,
        decompose_fn=lambda _mp4, out_dir: {"video_md": "Beat 1: Hook", "timeline_md": "0-2s", "storyboard": None},
    )
    assert bp_video["analysis_mode"] == "video"
    assert abs(float(bp_video["reference_duration_s"]) - 6.0) < 0.4
    assert bp_video["audio_mode"] == "asmr_original"
    assert bp_video["hook_layout"] == "kinetic_words"
    assert bp_video["energy_level"] == "energetic"

    bp_meta = analyse_trend_item(
        paths,
        2,
        vision_provider=prov,
        writer_provider=prov,
        downloader_fn=lambda _u, _dest: False,
    )
    assert bp_meta["analysis_mode"] == "metadata_only"


@pytest.mark.local
def test_audio_beats_mood_matching_ass_presets_and_smart_focus_reframe(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    # Synthesize a real 6s 120-BPM kick pulse (every 0.5s) and a calm ambient sine wave
    drum_wav = tmp_path / "upbeat_120bpm_beat.wav"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=0.8*exp(-20*mod(t\\,0.5))*sin(2*PI*110*t):s=48000:d=6.0",
            str(drum_wav),
        ]
    )
    calm_wav = tmp_path / "calm_piano_ambient.wav"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=48000:duration=6.0",
            "-af",
            "volume=0.15",
            str(calm_wav),
        ]
    )

    beat_info = analyse_music_beats(drum_wav, title_hint="upbeat drum beat")
    assert 112.0 <= float(beat_info["bpm"]) <= 128.0
    assert beat_info["energy_level"] == "energetic"
    assert len(beat_info["beat_times_s"]) >= 8
    assert len(beat_info["strong_beats_s"]) >= 2

    # Snap shot cuts onto the 0.5s beat grid while respecting [start_s, end_s]
    snapped = snap_shots_to_beats(
        [
            {"shot_id": 1, "start_s": 0.0, "duration_s": 1.62, "text": "Mở đầu"},
            {"shot_id": 2, "start_s": 0.0, "duration_s": 1.43, "text": "Tiếp theo"},
        ],
        {1: (0.0, 4.0), 2: (0.0, 4.0)},
        [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
    )
    assert snapped[0]["duration_s"] == 1.5
    assert snapped[1]["duration_s"] == 1.5

    # Import both tracks and verify mood/energy matching
    energetic_id = import_audio_asset(paths, drum_wav, kind="music", title="Upbeat Fast Groove")
    calm_id = import_audio_asset(paths, calm_wav, kind="music", title="Calm Soft Piano")

    picked_fast = pick_music_asset_record(paths, music_mood="Sôi động, nhanh", energy_level="energetic")
    picked_calm = pick_music_asset_record(paths, music_mood="Nhẹ nhàng, êm ái", energy_level="calm")
    assert picked_fast is not None and picked_fast["id"] == energetic_id
    assert picked_calm is not None and picked_calm["id"] == calm_id

    # Verify all 4 ASS subtitle presets & smart landscape crop with focus_x
    sample_events = [
        SubtitleEvent(start_s=0.0, end_s=2.0, text="Một chiếc nhẫn bạc làm hoàn toàn bằng tay"),
        SubtitleEvent(start_s=2.0, end_s=4.5, text="Từng nét chạm giữ trọn ánh bạc tự nhiên"),
    ]
    ass_center = build_ass(sample_events, layout_preset="big_center_title")
    ass_top = build_ass(sample_events, layout_preset="top_banner")
    ass_kinetic = build_ass(sample_events, layout_preset="kinetic_words")
    ass_clean = build_ass(sample_events, layout_preset="clean_bottom")

    assert "Dialogue: 0,0:00:00.00,0:00:02.00,HookCenter" in ass_center
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,HookTop" in ass_top
    assert ass_kinetic.count("Dialogue:") >= 3  # longer lines split into kinetic phrase chunks
    assert "HookCenter," in ass_clean and "Dialogue: 0,0:00:00.00,0:00:02.00,Default" in ass_clean

    smart_crop_args = build_segment_filter_args(
        orientation="landscape",
        width=1920,
        height=1080,
        crop_cfg={"mode": "smart_crop"},
        focus_x=0.85,
    )
    assert smart_crop_args[0] == "-vf"
    assert "crop=608:1080:1115:0" in smart_crop_args[1]
    validate_filtergraph_allowed(smart_crop_args[1])

    # Verify updated LIB_TSX passes static BR-PRD-02 product accuracy scanner
    assert scan_tsx_for_product_violations(LIB_TSX, "lib.tsx") == []


class _FastTrendWriter:
    def generate_json(self, prompt: str, schema: Any) -> Any:
        if schema is FactCheckResult:
            return schema.model_validate({"unverified_claims": []})
        cap = {"text": "Chế tác nhẫn bạc thủ công", "hashtags": ["trangsucbac", "handmade", "bac925"]}
        return schema.model_validate(
            {
                "plans": [
                    {
                        "formula": "asmr-craft",
                        "title": "Âm thanh chế tác",
                        "shots": [
                            {"shot_id": 10, "start_s": 0.0, "duration_s": 1.62, "text": "Chạm từng đường nét trên phôi bạc"},
                            {"shot_id": 11, "start_s": 0.0, "duration_s": 1.91, "text": "Ánh bạc mộc hoàn thiện thủ công"},
                        ],
                        "captions": {p: cap for p in ("facebook", "instagram", "threads", "tiktok")},
                    }
                ]
            }
        )


@pytest.mark.local
def test_ffmpeg_enhanced_cut_pace_guard_beat_sync_and_asmr_render(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    pid = create_product(paths.db_file, name="Nhẫn Bạc Trơn", material="Bạc S925", facts={})
    fid_p = import_footage_file(paths, CLIP_PORTRAIT, product_ids=[pid], enqueue_analysis=False)
    fid_l = import_footage_file(paths, CLIP_LANDSCAPE, product_ids=[pid], enqueue_analysis=False)
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE footage SET crop_json = ? WHERE id = ?", (json.dumps({"mode": "smart_crop"}), fid_l))
        conn.execute(
            """
            INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, tags_json, has_product, product_ids_json, focus_x)
            VALUES
                (10, ?, 1, 0.0, 3.0, 'Cận cảnh giũa nhẫn', '["craft","closeup"]', 1, ?, 0.5),
                (11, ?, 1, 0.0, 3.5, 'Cảnh ngang bàn thợ', '["craft","bench"]', 1, ?, 0.8),
                (12, ?, 2, 3.0, 6.0, 'Nhẫn hoàn thiện', '["product","closeup"]', 1, ?, 0.5)
            """,
            (fid_p, f"[{pid}]", fid_l, f"[{pid}]", fid_p, f"[{pid}]"),
        )

    # 1. Cut-pace validator rejects a sluggish 5.8s single-shot plan when trend cut_pace_s is 1.2s
    cap = {"text": "Nhẫn bạc", "hashtags": ["bac"]}
    sluggish_item = VideoPlanItem.model_validate(
        {
            "formula": "fast-cut",
            "title": "Quá chậm",
            "shots": [{"shot_id": 10, "start_s": 0.0, "duration_s": 5.8, "text": "Một cảnh dài"}],
            "captions": {p: cap for p in ("facebook", "instagram", "threads", "tiktok")},
        }
    )
    shot_map = {
        10: {"id": 10, "start_s": 0.0, "end_s": 6.0, "product_ids": [pid], "tags": [], "has_product": 1},
        11: {"id": 11, "start_s": 0.0, "end_s": 5.0, "product_ids": [pid], "tags": [], "has_product": 1},
        12: {"id": 12, "start_s": 0.0, "end_s": 6.0, "product_ids": [pid], "tags": [], "has_product": 1},
    }
    with pytest.raises(ValueError, match="exceeds trend cut pace limit"):
        validate_and_normalize_plan(
            sluggish_item,
            shot_map=shot_map,
            product_map={pid: {"id": pid, "name": "Nhẫn Bạc Trơn"}},
            voice_lang="none",
            caption_lang="vi",
            target_duration_s=6.0,
            reference_cut_pace_s=1.2,
        )

    # 2. Import 120 BPM rhythmic music and render a Trend Blueprint video via FFmpeg Enhanced
    drum_wav = tmp_path / "rhythm.wav"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=0.7*exp(-20*mod(t\\,0.5))*sin(2*PI*110*t):s=48000:d=8.0",
            str(drum_wav),
        ]
    )
    import_audio_asset(paths, drum_wav, kind="music", title="Energetic Craft Beat")

    blueprint = {
        "hook": "Mở đầu tiếng giũa bạc thật",
        "structure": [{"t": "0-2s", "duration_s": 1.5, "role": "hook", "what": "Giũa nhẫn", "visual_tags": ["craft"]}],
        "cut_pace_s": 1.7,
        "text_style": "Chữ nhảy theo nhịp",
        "music_mood": "Sôi động",
        "why_it_works": "Bắt tai và chân thật",
        "analysis_mode": "video",
        "reference_duration_s": 5.5,
        "audio_mode": "asmr_original",
        "hook_layout": "kinetic_words",
        "energy_level": "energetic",
    }
    writer = _FastTrendWriter()
    vids = create_remix_plans(
        paths,
        None,
        count=1,
        voice_lang="none",
        caption_lang="vi",
        target_duration_s=5.5,
        formula={"formula": "asmr-craft", "trend_analysis": blueprint, "recommended_shot_ids": [10, 11]},
        writer_provider=writer,
        checker_provider=writer,
    )
    assert len(vids) == 1
    render_video(paths, vids[0], preset="ultrafast")
    v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (vids[0],))
    assert v_row is not None and v_row["status"] == "pending_approval"
    master_info = inspect_master_streams(paths.media_dir / str(v_row["output_path"]))
    assert (master_info["width"], master_info["height"]) == (1080, 1920)
    # 1.62s + 1.91s = 3.53s raw -> snapped onto 0.5s beats (1.5s + 2.0s = 3.5s)
    assert abs(float(master_info["duration_s"]) - 3.5) < 0.25


class _SuggestionBatchWriter:
    def generate_json(self, prompt: str, schema: type[SuggestionsBatchSchema]) -> SuggestionsBatchSchema:
        assert "HIỆU SUẤT THỰC TẾ 72H TRÊN KÊNH" in prompt
        return schema.model_validate(
            {
                "suggestions": [
                    {
                        "trend_item_id": 1,
                        "text": "Dựng mở đầu tiêu đề lớn kèm cận cảnh nhẫn bạc theo nhịp nhanh",
                        "formula_name": "kinetic-closeup",
                        "recommended_shot_ids": [1, 2],
                        "beat_shot_map": [
                            {"beat_index": 0, "shot_id": 1, "role": "hook"},
                            {"beat_index": 1, "shot_id": 2, "role": "payoff"},
                        ],
                        "missing_shots": "",
                    },
                    {
                        "trend_item_id": 2,
                        "text": "Dựng biến thể thứ hai từ kênh YouTube",
                        "formula_name": "craft-process",
                        "recommended_shot_ids": [1, 2],
                        "beat_shot_map": [],
                        "missing_shots": "",
                    },
                ]
            }
        )


class _ApiStudioProvider:
    """Real structured-output provider object exercising `studio/api_agent.py` + `ai_usage` spend tracking."""

    name = "claude_api"
    route_kind = "api"

    def __init__(self, db_file: Path) -> None:
        self.db_file = db_file
        self.calls: list[str] = []

    def generate_json(self, prompt: str, schema: Any) -> Any:
        record_usage(
            self.db_file,
            provider="claude_api",
            model="claude-opus-5-5",
            kind="studio",
            route="api",
            units_in=1000,
            units_out=500,
            cost_usd=0.014,
        )
        if schema is FactCheckResult:
            return schema.model_validate({"unverified_claims": []})
        if schema is StudioPlanGenSchema:
            self.calls.append("plan")
            assert "trend_blueprint" in prompt
            cap = {"text": "Nhẫn bạc chế tác thủ công", "hashtags": ["trangsucbac", "bacmynghe", "handmade"]}
            return schema.model_validate(
                {
                    "title": "Ánh Bạc Thủ Công",
                    "formula": "kinetic-closeup",
                    "scenes": [
                        {"shot_id": 1, "start_s": 0.0, "duration_s": 2.0, "text": "Chạm khắc từng đường nét"},
                        {"shot_id": 2, "start_s": 3.0, "duration_s": 2.0, "text": "Giữ nguyên ánh bạc mộc"},
                    ],
                    "captions": {p: cap for p in ("facebook", "instagram", "threads", "tiktok")},
                }
            )
        if schema is StudioSceneGenSchema:
            self.calls.append("scene_v1")
            scene_v1 = """import React from 'react';
import { AbsoluteFill, Sequence } from 'remotion';
import { FontFace, ProductShot, Subtitle } from './lib';
import { PLAN } from './plan';

export const Scene: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: '#000' }}>
    <FontFace />
    {PLAN.scenes.map((scene, idx) => (
      <Sequence key={idx} from={scene.fromFrame} durationInFrames={scene.durationFrames}>
        <ProductShot file={scene.file} startS={scene.startS} />
        <Subtitle text={scene.text} />
      </Sequence>
    ))}
  </AbsoluteFill>
);
"""
            assert scan_scene_contract(scene_v1) == []
            return schema.model_validate({"scene_tsx": f"```tsx\n{scene_v1}\n```"})
        if schema is StudioReviseGenSchema:
            self.calls.append("revise_v2")
            assert "Độ bám xu hướng" in prompt
            scene_v2 = """import React from 'react';
import { AbsoluteFill, Sequence } from 'remotion';
import { FontFace, HookTitle, KineticSubtitle, ProductShot } from './lib';
import { PLAN } from './plan';

export const Scene: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: '#000' }}>
    <FontFace />
    {PLAN.scenes.map((scene, idx) => (
      <Sequence key={idx} from={scene.fromFrame} durationInFrames={scene.durationFrames}>
        <ProductShot file={scene.file} startS={scene.startS} />
        {idx === 0 ? (
          <HookTitle text={scene.text} />
        ) : (
          <KineticSubtitle text={scene.text} durationFrames={scene.durationFrames} />
        )}
      </Sequence>
    ))}
  </AbsoluteFill>
);
"""
            assert scan_scene_contract(scene_v2) == []
            return schema.model_validate({"update_plan": False, "update_scene": True, "scene_tsx": scene_v2})
        raise AssertionError(f"Unexpected schema {schema}")


class _TrendVisionScorer:
    name = "claude_api"
    route_kind = "api"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._attempt = 0

    def describe_video(self, video: Path, prompt: str, schema: Any, *, thumbnails: list[Path] | None = None) -> Any:
        self._attempt += 1
        thumbs = [Path(p) for p in (thumbnails or [])]
        self.calls.append({"prompt": prompt, "thumbs": thumbs, "schema": schema})
        assert schema is TrendVideoQualityScore
        assert "Độ bám xu hướng" in prompt
        # First render (v1) gets low trend_alignment (4/10 -> overall 6.8 < 8.0), triggering Studio self-revision!
        if self._attempt == 1:
            return schema.model_validate(
                {
                    "can_judge": True,
                    "hook": {"evidence": "0.3s thấy nhẫn rõ", "score": 8},
                    "product_clarity": {"evidence": "1.3s ánh bạc nét", "score": 8},
                    "text_safe_zone": {"evidence": "chữ gọn vùng dưới", "score": 7},
                    "pacing_sync": {"evidence": "nhịp ổn", "score": 7},
                    "trend_alignment": {"evidence": "0.3s thiếu HookTitle mở đầu theo mẫu big_center_title", "score": 4},
                    "notes": "Cần thêm tiêu đề mở đầu lớn và chữ động theo mẫu xu hướng.",
                }
            )
        # Second render (v2) after Studio self-revision scores 9.0/10!
        return schema.model_validate(
            {
                "can_judge": True,
                "hook": {"evidence": "0.3s HookTitle bật nảy cùng nhẫn", "score": 9},
                "product_clarity": {"evidence": "ánh bạc mộc rõ nét", "score": 9},
                "text_safe_zone": {"evidence": "gọn trong SAFE", "score": 9},
                "pacing_sync": {"evidence": "cắt đúng phách nhạc", "score": 9},
                "trend_alignment": {"evidence": "khớp big_center_title và kinetic_words của mẫu", "score": 9},
                "notes": "Bản dựng bám sát xu hướng và giữ nguyên màu sản phẩm.",
            }
        )


@pytest.mark.local
def test_end_to_end_trend_to_studio_api_router_trend_alignment_and_auto_revision(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node.js is required for real Remotion rendering")

    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths

    # Configure API key + auto_produce_top_n=1 + studio_preferred + api_fallback="auto"
    secrets = SecretsStore(paths.secrets_file)
    secrets.set("ANTHROPIC_API_KEY", "sk-ant-test-local-key")

    cfg = load_settings(paths.config_file)
    cfg.ai.policy.api_fallback = "auto"
    cfg.ai.routes.studio = ["claude_api"]
    cfg.trends.auto_produce_top_n = 1
    cfg.trends.render_mode = "studio_preferred"
    cfg.quality.min_score = 8.0
    cfg.quality.max_retries = 1
    save_settings(paths.config_file, cfg)

    ok_ed, which_prov = can_start_studio_editor(paths, cfg, secrets_store=secrets)
    assert ok_ed is True and which_prov == "claude_api"

    # Populate product, real footage shots, 120 BPM music asset, and 72h historical winning post metrics
    pid = create_product(paths.db_file, name="Nhẫn Bạc Cổ Điển", material="Bạc S925", facts={})
    fid = import_footage_file(paths, CLIP_PORTRAIT, product_ids=[pid], enqueue_analysis=False)
    drum_wav = tmp_path / "studio_beat.wav"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=0.75*exp(-20*mod(t\\,0.5))*sin(2*PI*110*t):s=48000:d=6.0",
            str(drum_wav),
        ]
    )
    music_id = import_audio_asset(paths, drum_wav, kind="music", title="Upbeat Silver Beat")

    blueprint = {
        "hook": "Tiêu đề nổi bật trên cận cảnh nhẫn bạc",
        "structure": [
            {"t": "0-2s", "duration_s": 2.0, "role": "hook", "what": "Cận cảnh nhẫn", "visual_tags": ["closeup"]},
            {"t": "2-4s", "duration_s": 2.0, "role": "payoff", "what": "Góc nghiêng ánh bạc", "visual_tags": ["product"]},
        ],
        "cut_pace_s": 2.0,
        "text_style": "Tiêu đề lớn mở đầu + phụ đề sáng từng từ",
        "music_mood": "Sôi động, bắt beat",
        "why_it_works": "Thu hút mắt nhìn trong 1 giây đầu",
        "analysis_mode": "video",
        "reference_duration_s": 4.0,
        "audio_mode": "music_only",
        "hook_layout": "big_center_title",
        "energy_level": "energetic",
    }

    # Create a real storyboard JPEG in reference/rea_1 to verify Vision receives it during scoring
    rea_dir = paths.media_dir / "reference" / "rea_1"
    rea_dir.mkdir(parents=True, exist_ok=True)
    storyboard_jpg = rea_dir / "storyboard.jpg"
    run_ffmpeg(["-ss", "0.5", "-i", str(CLIP_PORTRAIT), "-frames:v", "1", str(storyboard_jpg)])

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, tags_json, has_product, quality, product_ids_json)
            VALUES
                (1, ?, 1, 0.0, 3.0, 'Cận cảnh nhẫn bạc', '["closeup","product"]', 1, 5, ?),
                (2, ?, 2, 3.0, 6.0, 'Góc nghiêng ánh bạc', '["product"]', 1, 4, ?)
            """,
            (fid, f"[{pid}]", fid, f"[{pid}]"),
        )
        # Historical posted video + 72h metrics to exercise winning_formulas_summary()
        conn.execute(
            "INSERT INTO accounts (id, platform, external_id, name, secret_key) VALUES (1, 'tiktok', 'tt_acc_1', 'SilverVN', 'TT_TOKEN')"
        )
        conn.execute(
            "INSERT INTO videos (id, status, plan_json, captions_json) VALUES (90, 'posted', '{\"formula\":\"kinetic-closeup\",\"shots\":[]}', '{}')"
        )
        conn.execute(
            "INSERT INTO posts (id, video_id, account_id, scheduled_at, status) VALUES (90, 90, 1, '2026-11-10T00:00:00Z', 'posted')"
        )
        conn.execute(
            "INSERT INTO post_metrics (post_id, checkpoint, views, likes, shares) VALUES (90, '72h', 18000, 950, 210)"
        )
        conn.execute(
            """
            INSERT INTO trend_items (id, source, external_id, url, author, published_at, score, analysis_json)
            VALUES
                (1, 'tiktok', 'tt_1', 'https://tiktok.com/1', 'Maker1', '2026-11-17T00:00:00Z', 95.0, ?),
                (2, 'youtube', 'yt_2', 'https://youtube.com/2', 'Maker2', '2026-11-17T00:00:00Z', 82.0, ?)
            """,
            (json.dumps(blueprint, ensure_ascii=False), json.dumps(blueprint, ensure_ascii=False)),
        )
        conn.execute(
            "INSERT INTO reference_videos (trend_item_id, path, rea_dir, downloaded_at) VALUES (1, 'reference/ref_1.mp4', 'reference/rea_1', '2026-11-17T00:00:00Z')"
        )

    winners = winning_formulas_summary(paths.db_file)
    assert len(winners) == 1 and winners[0]["formula"] == "kinetic-closeup"

    # 1. make_suggestions with auto_produce_top_n=1 auto-accepts suggestion #1 into Studio!
    sids = make_suggestions(paths, writer_provider=_SuggestionBatchWriter(), max_suggestions=2)
    assert len(sids) == 2

    s1_row = query_one(paths.db_file, "SELECT * FROM suggestions WHERE id = ?", (sids[0],))
    s2_row = query_one(paths.db_file, "SELECT * FROM suggestions WHERE id = ?", (sids[1],))
    assert s1_row is not None and s1_row["status"] == "accepted"
    assert s2_row is not None and s2_row["status"] == "new"

    studio_sess = query_one(paths.db_file, "SELECT * FROM studio_sessions ORDER BY id DESC LIMIT 1")
    assert studio_sess is not None
    assert int(studio_sess["ref_item_id"]) == 1
    sess_opts = json.loads(studio_sess["options_json"])
    assert sess_opts["auto_run"] is True
    assert sess_opts["music_asset_id"] == music_id

    # 2. Accepting suggestion #2 while Studio is busy automatically falls back to FFmpeg Enhanced (`plan` job)!
    fallback_job = accept_suggestion(paths, sids[1], count=1, auto_render=True, actor="ui")
    assert fallback_job is not None
    plan_jobs = query_all(paths.db_file, "SELECT * FROM jobs WHERE kind = 'plan'")
    assert len(plan_jobs) == 1

    # 3. Execute Studio session #1 via API-routed Studio generator + real Remotion + Vision auto-revision!
    api_prov = _ApiStudioProvider(paths.db_file)
    studio_gen = make_studio_generator(paths, cfg, secrets_store=secrets, provider_overrides={"claude_api": api_prov})
    vision_scorer = _TrendVisionScorer()

    res = run_studio_job(
        paths,
        int(studio_sess["id"]),
        code_generator=studio_gen,
        checker_provider=api_prov,
        vision_provider=vision_scorer,
    )
    assert res["status"] == "done"
    assert res["version"] == 2  # v1 scored 6.8 (<8.0) -> auto-revised to v2 (9.0/10)!
    assert api_prov.calls == ["plan", "scene_v1", "revise_v2"]
    assert len(vision_scorer.calls) == 2
    # Storyboard JPEG was appended to thumbnails for Vision trend_alignment comparison!
    assert vision_scorer.calls[0]["thumbs"][-1].name == "storyboard.jpg"

    final_video = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (studio_sess["video_id"],))
    assert final_video is not None
    assert final_video["status"] == "pending_approval"
    assert final_video["engine"] == "studio"
    assert float(final_video["quality_score"]) == 9.0
    captions = json.loads(final_video["captions_json"])
    assert set(captions) == {"facebook", "instagram", "threads", "tiktok"}

    master_meta = inspect_master_streams(paths.media_dir / str(final_video["output_path"]))
    assert (master_meta["width"], master_meta["height"]) == (1080, 1920)
    assert abs(float(master_meta["duration_s"]) - 4.0) < 0.25

    # Verify 5-criterion TrendVideoQualityScore helper math directly
    low_res = TrendVideoQualityScore.model_validate(
        {
            "can_judge": True,
            "hook": {"evidence": "ok", "score": 9},
            "product_clarity": {"evidence": "ok", "score": 9},
            "text_safe_zone": {"evidence": "ok", "score": 8},
            "pacing_sync": {"evidence": "ok", "score": 9},
            "trend_alignment": {"evidence": "chưa khớp bố cục chữ", "score": 5},
            "notes": "Cần bám sát bố cục mẫu",
        }
    )
    assert overall_from(low_res) == 8.0
    assert weakest_hint(low_res).startswith("Độ bám xu hướng 5/10:")
