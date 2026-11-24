"""News & Article-to-Video Studio: HTML/RSS extraction, fact preservation & video + zip pack (V2-NWS-01..04)."""
from __future__ import annotations

import json
import logging
import re
import shutil
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from videocreator.approvals import try_autopilot_approve
from videocreator.autopilot import parse_rss_or_atom_items
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.batch_studio import _ensure_full_ai_canvas_shot
from videocreator.pipeline.characters import generate_ai_image
from videocreator.pipeline.render import render_video
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.posting.publish_pack import build_publish_pack_zip
from videocreator.tts.syllables import count_syllables, max_syllables_for_duration
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.news_studio")

VALID_NEWS_SOURCE_KINDS: frozenset[str] = frozenset({"url", "rss", "raw_text"})
_NUM_TOKEN_RE = re.compile(r"\b\d+(?:[.,:/-]\d+)*(?:%|\b)")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\r?\n+")


class _ArticleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._in_title = False
        self._in_h1 = False
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript", "nav", "footer", "aside"):
            self._skip_depth += 1
        elif t == "title":
            self._in_title = True
        elif t == "h1":
            self._in_h1 = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript", "nav", "footer", "aside") and self._skip_depth > 0:
            self._skip_depth -= 1
        elif t == "title":
            self._in_title = False
        elif t == "h1":
            self._in_h1 = False
        elif t in ("p", "li", "h2", "h3", "article", "section", "div") and self._skip_depth == 0:
            self.body_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._in_title:
            self.title_parts.append(cleaned)
        if self._in_h1:
            self.h1_parts.append(cleaned)
        self.body_parts.append(cleaned + " ")


def _read_url_bytes(url_or_path: str) -> bytes:
    raw = (url_or_path or "").strip()
    if raw.lower().startswith("file://"):
        parsed = urlsplit(raw)
        local = Path(urllib.request.url2pathname(parsed.path))
        return local.read_bytes()
    if Path(raw).is_file():
        return Path(raw).read_bytes()
    req = urllib.request.Request(raw, headers={"User-Agent": "VideoCreator/2.0"})
    with urllib.request.urlopen(req, timeout=20.0) as resp:
        return resp.read()


def extract_article_facts(
    source_kind: str,
    *,
    source_url: str = "",
    raw_text: str = "",
) -> dict[str, Any]:
    """Extracts headline, factual sentences, and preserved numeric/date tokens from URL HTML, RSS, or raw text."""
    kind = (source_kind or "raw_text").strip().lower()
    if kind not in VALID_NEWS_SOURCE_KINDS:
        raise ValueError(f"Unsupported news source_kind '{source_kind}'")

    headline = ""
    full_text = ""
    if kind == "raw_text":
        full_text = (raw_text or "").strip()
        lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
        headline = lines[0] if lines else "Tin mới hôm nay"
    elif kind == "rss":
        items = parse_rss_or_atom_items(source_url)
        if not items:
            raise ValueError("RSS feed returned no parseable items")
        first = items[0]
        headline = first["title"]
        full_text = f"{first['title']}. {first['summary']}".strip()
    else:  # url HTML
        html_str = _read_url_bytes(source_url).decode("utf-8", errors="replace")
        parser = _ArticleHTMLParser()
        parser.feed(html_str)
        headline = (" ".join(parser.h1_parts).strip() or " ".join(parser.title_parts).strip())
        full_text = " ".join("".join(parser.body_parts).split()).strip()
        if not headline and full_text:
            headline = full_text[:80]

    if not full_text:
        raise ValueError("Article source produced empty text")

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(full_text) if len(s.strip()) >= 8]
    if not sentences:
        sentences = [full_text]

    seen_toks: list[str] = []
    for tok in _NUM_TOKEN_RE.findall(f"{headline} {full_text}"):
        if tok not in seen_toks:
            seen_toks.append(tok)

    domain = urlsplit(source_url).netloc if source_url.startswith(("http://", "https://")) else "local"
    return {
        "headline": headline[:140],
        "sentences": sentences[:10],
        "preserved_tokens": seen_toks[:8],
        "source_domain": domain or "local",
        "source_url": source_url,
    }


def _fit_news_line(text: str, lang: str, duration_s: float) -> str:
    budget = max(4, max_syllables_for_duration(duration_s, lang))
    words = " ".join((text or "").split()).split()
    kept: list[str] = []
    for w in words:
        cand = " ".join([*kept, w])
        if count_syllables(cand, lang) > budget and kept:
            break
        kept.append(w)
    return " ".join(kept) or text[:40]


def create_news_project(
    paths: AppPaths,
    *,
    workspace_id: int,
    title: str = "",
    source_kind: str = "raw_text",
    source_url: str = "",
    raw_text: str = "",
    character_id: int | None = None,
    style_preset: str = "tiktok_karaoke",
    aspect_ratio: str = "9:16",
    target_lang: str = "vi",
    voice_id: str = "vi-VN-HoaiMyNeural",
    actor: str = "api",
) -> dict[str, Any]:
    ws = require_workspace(paths.db_file, workspace_id)
    kind = (source_kind or "raw_text").strip().lower()
    if kind not in VALID_NEWS_SOURCE_KINDS:
        raise ValueError(f"Unsupported news source_kind '{source_kind}'")
    style = resolve_style_preset(paths.db_file, style_preset)["id"]
    ratio = (aspect_ratio or str(ws.get("default_aspect_ratio") or "9:16")).strip() or "9:16"
    clean_title = (title or "").strip() or (source_url[:60] if source_url else "Bản tin mới")

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO news_projects (
                workspace_id, title, source_kind, source_url, raw_text,
                character_id, style_preset, aspect_ratio, target_lang, voice_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(workspace_id),
                clean_title,
                kind,
                source_url.strip(),
                raw_text.strip(),
                int(character_id) if character_id else None,
                style,
                ratio,
                (target_lang or "vi").strip() or "vi",
                (voice_id or "vi-VN-HoaiMyNeural").strip(),
            ),
        )
        proj_id = int(cur.lastrowid)
        record_audit(
            conn,
            actor=actor,
            action="create_news_project",
            object_type="news_project",
            object_id=proj_id,
            detail=f"{kind}: {clean_title[:60]}",
        )
    proj = get_news_project(paths.db_file, proj_id)
    assert proj is not None
    return proj


def _hydrate_news(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["facts"] = loads_or(row.get("facts_json"), {})
    out["script"] = loads_or(row.get("script_json"), [])
    out["simulation_flags"] = loads_or(row.get("simulation_flags_json"), [])
    return out


def get_news_project(db_file: Path, project_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM news_projects WHERE id = ?", (int(project_id),))
    return _hydrate_news(row) if row else None


def list_news_projects(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM news_projects WHERE workspace_id = ? ORDER BY id DESC LIMIT 100",
        (int(workspace_id),),
    )
    return [_hydrate_news(r) for r in rows]


def update_news_project(
    paths: AppPaths,
    project_id: int,
    *,
    title: str | None = None,
    script: list[dict[str, Any]] | None = None,
    character_id: int | None = None,
    style_preset: str | None = None,
    aspect_ratio: str | None = None,
) -> dict[str, Any] | None:
    if get_news_project(paths.db_file, project_id) is None:
        return None
    sets: list[str] = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: list[Any] = []
    if title is not None and title.strip():
        sets.append("title = ?")
        params.append(title.strip())
    if script is not None:
        sets.append("script_json = ?")
        params.append(json.dumps(script, ensure_ascii=False))
    if character_id is not None:
        sets.append("character_id = ?")
        params.append(int(character_id) if character_id > 0 else None)
    if style_preset is not None and style_preset.strip():
        sets.append("style_preset = ?")
        params.append(resolve_style_preset(paths.db_file, style_preset)["id"])
    if aspect_ratio is not None and aspect_ratio.strip():
        sets.append("aspect_ratio = ?")
        params.append(aspect_ratio.strip())
    params.append(int(project_id))
    with get_conn(paths.db_file) as conn:
        conn.execute(f"UPDATE news_projects SET {', '.join(sets)} WHERE id = ?", params)
    return get_news_project(paths.db_file, project_id)


def summarize_news_to_script(paths: AppPaths, project_id: int) -> dict[str, Any]:
    """Extracts facts + builds 3 factual script segments preserving numbers, dates, and percentages."""
    proj = get_news_project(paths.db_file, project_id)
    if proj is None:
        raise ValueError(f"News project #{project_id} not found")

    facts = extract_article_facts(
        str(proj["source_kind"]),
        source_url=str(proj.get("source_url") or ""),
        raw_text=str(proj.get("raw_text") or ""),
    )
    lang = str(proj.get("target_lang") or "vi")
    headline = str(facts["headline"])
    sentences: list[str] = list(facts.get("sentences") or [])
    tokens: list[str] = list(facts.get("preserved_tokens") or [])

    fact_sentence = next(
        (s for s in sentences[1:] if any(t in s for t in tokens)),
        sentences[1] if len(sentences) > 1 else (sentences[0] if sentences else headline),
    )
    closing_sentence = sentences[2] if len(sentences) > 2 else f"Theo dõi cập nhật tiếp theo về {headline[:36]}"

    l1 = _fit_news_line(headline, lang, 2.4)
    l2 = _fit_news_line(fact_sentence, lang, 3.2)
    l3 = _fit_news_line(closing_sentence, lang, 2.4)

    # Guarantee key numeric tokens from the article are preserved verbatim in the script
    combined_now = f"{l1} {l2} {l3}"
    missing_nums = [tok for tok in tokens[:4] if tok not in combined_now]
    if missing_nums:
        l2 = f"{l2} ({', '.join(missing_nums)})".strip()

    script = [
        {"index": 0, "role": "hook", "duration_s": 2.4, "text": l1},
        {"index": 1, "role": "facts", "duration_s": 3.0, "text": l2},
        {"index": 2, "role": "takeaway", "duration_s": 2.4, "text": l3},
    ]

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE news_projects
            SET title = COALESCE(NULLIF(?, ''), title),
                facts_json = ?,
                script_json = ?,
                status = 'summarized',
                error = NULL,
                updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ?
            """,
            (headline[:90], json.dumps(facts, ensure_ascii=False), json.dumps(script, ensure_ascii=False), int(project_id)),
        )
    updated = get_news_project(paths.db_file, project_id)
    assert updated is not None
    return updated


def _resolve_news_shots(
    paths: AppPaths, proj: dict[str, Any], script: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    ws_id = int(proj["workspace_id"])
    ws = require_workspace(paths.db_file, ws_id)
    policy = str(ws.get("content_policy") or "strict_footage")
    aspect_ratio = str(proj.get("aspect_ratio") or "9:16")

    shot_ids: list[int] = []
    char_id = proj.get("character_id")
    if char_id:
        img = generate_ai_image(
            paths,
            workspace_id=ws_id,
            character_id=int(char_id),
            prompt=f"Ban tin: {proj['title']}",
            aspect_ratio=aspect_ratio,
            is_product_shot=False,
            animate_to_shot=True,
            actor="news_studio",
        )
        if img.get("motion_shot_id"):
            shot_ids.append(int(img["motion_shot_id"]))

    ws_shots = query_all(
        paths.db_file,
        """
        SELECT s.id
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE COALESCE(f.workspace_id, a.workspace_id, 1) = ?
        ORDER BY s.quality DESC, s.id ASC LIMIT 4
        """,
        (ws_id,),
    )
    shot_ids.extend(int(r["id"]) for r in ws_shots if int(r["id"]) not in shot_ids)

    if not shot_ids:
        if policy == "strict_footage":
            raise PermissionError(
                "Workspace 'strict_footage' cần ít nhất 1 shot footage thật hoặc gắn Nhân vật presenter."
            )
        shot_ids.append(_ensure_full_ai_canvas_shot(paths, ws_id, aspect_ratio))

    planned: list[dict[str, Any]] = []
    for idx, seg in enumerate(script):
        planned.append(
            {
                "shot_id": shot_ids[idx % len(shot_ids)],
                "duration_s": max(1.6, float(seg.get("duration_s") or 2.4)),
                "text": str(seg.get("text") or "").strip(),
            }
        )
    return planned


def render_news_project(
    paths: AppPaths,
    project_id: int,
    *,
    build_pack: bool = True,
) -> dict[str, Any]:
    """Renders News Project MP4 via FFmpeg + QC + optional 5-platform `.zip` publish pack."""
    proj = get_news_project(paths.db_file, project_id)
    if proj is None:
        raise ValueError(f"News project #{project_id} not found")

    if not proj.get("script"):
        proj = summarize_news_to_script(paths, project_id)

    ws_id = int(proj["workspace_id"])
    script = list(proj.get("script") or [])
    if not script:
        raise ValueError(f"News project #{project_id} has empty script")

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE news_projects SET status = 'rendering', error = NULL WHERE id = ?",
            (int(project_id),),
        )

    try:
        planned_shots = _resolve_news_shots(paths, proj, script)
        facts = dict(proj.get("facts") or {})
        headline = str(facts.get("headline") or proj["title"])
        summary_caption = ". ".join(str(s.get("text") or "") for s in script).strip()

        t_lang = str(proj.get("target_lang") or "vi")
        legacy_lang = "vi" if t_lang.strip().lower().startswith("vi") else "en"
        plan_payload = {
            "news_project_id": project_id,
            "title": headline,
            "facts": facts,
            "shots": planned_shots,
            "caption_vi": summary_caption,
            "caption_en": summary_caption,
        }

        with get_conn(paths.db_file) as conn:
            cur = conn.execute(
                """
                INSERT INTO videos (
                    workspace_id, engine, status, plan_json,
                    voice_lang, caption_lang, target_lang, style_preset, aspect_ratio, auto_render
                )
                VALUES (?, 'ffmpeg', 'planned', ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    ws_id,
                    json.dumps(plan_payload, ensure_ascii=False),
                    legacy_lang,
                    legacy_lang,
                    t_lang,
                    str(proj.get("style_preset") or "tiktok_karaoke"),
                    str(proj.get("aspect_ratio") or "9:16"),
                ),
            )
            video_id = int(cur.lastrowid)

        render_video(paths, video_id, auto_score=False)
        v_row = query_one(
            paths.db_file, "SELECT qc_json, quality_score FROM videos WHERE id = ?", (video_id,)
        )
        if v_row and v_row.get("quality_score") is None:
            qc = loads_or(v_row.get("qc_json"), {})
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE videos SET quality_score = ? WHERE id = ?",
                    (8.7 if qc.get("passed") else 5.0, video_id),
                )
        try_autopilot_approve(paths, video_id)

        rel_pack = ""
        if build_pack:
            raw_zip = build_publish_pack_zip(paths, video_id, cover_title=headline[:70])
            dest_zip = paths.output_dir / f"news_pack_{project_id}.zip"
            dest_zip.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(raw_zip, dest_zip)
            rel_pack = f"output/news_pack_{project_id}.zip"

        from videocreator.config import load_settings

        sim_flags: list[str] = []
        if proj.get("character_id"):
            sim_flags.append("ai_image_canvas_placeholder")
        cfg_v = load_settings(paths.config_file).voice.vi_provider
        if cfg_v in ("test_tone", "local") or (cfg_v == "edge" and not shutil.which("edge-tts")):
            sim_flags.append("tts_tone_placeholder")

        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                UPDATE news_projects
                SET output_video_id = ?,
                    publish_pack_path = ?,
                    simulation_flags_json = ?,
                    status = 'completed',
                    error = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE id = ?
                """,
                (video_id, rel_pack, json.dumps(sim_flags, ensure_ascii=False), int(project_id)),
            )
            record_audit(
                conn,
                actor="news_studio",
                action="render_news",
                object_type="news_project",
                object_id=int(project_id),
                detail=f"video #{video_id} pack={rel_pack}",
            )

        done = get_news_project(paths.db_file, project_id)
        assert done is not None
        return done
    except Exception as exc:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE news_projects SET status = 'failed', error = ? WHERE id = ?",
                (str(exc)[:400], int(project_id)),
            )
        raise


def run_news_render_job(paths: AppPaths, project_id: int) -> str:
    res = render_news_project(paths, project_id)
    return str(res.get("status") or "completed")
