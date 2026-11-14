"""Local tests for the MoneyPrinterTurbo voice payload, config file and SRT parsing (Phase 09)."""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from videocreator.config import load_settings
from videocreator.engines.mpt_client import MPTClient
from videocreator.engines.mpt_service import mpt_dir, write_mpt_config
from videocreator.paths import get_paths
from videocreator.pipeline.subtitles import parse_srt


@pytest.mark.local
def test_mpt_config_binds_localhost_and_local_source(tmp_path: Path) -> None:
    if not (mpt_dir() / "config.example.toml").exists():
        pytest.skip("MoneyPrinterTurbo is not installed in tools/mpt")
    cfg = load_settings(get_paths(tmp_path).config_file)
    out_toml = write_mpt_config(cfg)
    with out_toml.open("rb") as f:
        parsed = tomllib.load(f)
    assert parsed["listen_host"] == "127.0.0.1"
    assert parsed["listen_port"] == cfg.mpt.port
    assert parsed["app"]["video_source"] == "local"
    assert parsed["app"]["subtitle_provider"] == "edge"


@pytest.mark.local
def test_voice_payload_carries_our_script_and_no_bgm() -> None:
    payload = MPTClient.build_voice_payload(
        script_text="  Chế tác nhẫn bạc thủ công  ",
        voice_name="vi-VN-HoaiMyNeural-Female",
        language="vi-VN",
    )
    assert payload["video_script"] == "Chế tác nhẫn bạc thủ công"
    assert payload["voice_name"] == "vi-VN-HoaiMyNeural-Female"
    assert payload["bgm_type"] == ""
    assert payload["video_source"] == "local"
    assert payload["voice_rate"] == 1.0


@pytest.mark.local
def test_parse_srt_reads_cues_written_by_mpt() -> None:
    # Verbatim subtitle.srt produced by MoneyPrinterTurbo v1.3.9 in spike S12.
    srt = (
        "1\n00:00:00,138 --> 00:00:00,962\nTừng đường giũa\n\n"
        "2\n00:00:01,150 --> 00:00:02,200\ntừng chút kiên nhẫn\n\n"
        "3\n00:00:03,075 --> 00:00:03,850\nĐeo lên tay\n\n"
        "4\n00:00:04,050 --> 00:00:05,388\nmang theo cả tâm hồn\n"
    )
    events = parse_srt(srt)
    assert [e.text for e in events] == ["Từng đường giũa", "từng chút kiên nhẫn", "Đeo lên tay", "mang theo cả tâm hồn"]
    assert events[0].start_s == pytest.approx(0.138)
    assert events[3].end_s == pytest.approx(5.388)
