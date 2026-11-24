"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Download, Play, RefreshCw, Save, Volume2 } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface SyllableEntry {
  shot_index: number;
  duration_s: number;
  text: string;
  syllables: number;
  max_syllables: number;
  over_budget: boolean;
  recommended_atempo: number;
}

interface VideoDetail {
  id: number;
  workspace_id: number;
  status: string;
  style_preset: string;
  aspect_ratio: "9:16" | "16:9" | "1:1";
  voice_lang: "none" | "vi" | "en";
  output_url: string | null;
  cover_url: string | null;
  duration_s: number | null;
  plan: {
    title?: string;
    shots?: Array<{ shot_id: number; start_s: number; duration_s: number; text: string }>;
  };
  qc: {
    passed?: boolean;
    integrated_lufs?: number | null;
    issues?: string[];
  };
  syllable_budget: SyllableEntry[];
  error: string | null;
}

interface StylePreset {
  id: string;
  name: string;
  subtitle_style: string;
}

export default function VideoDetailPage() {
  const params = useParams<{ id: string }>();
  const videoId = Number(params.id);

  const [video, setVideo] = useState<VideoDetail | null>(null);
  const [styles, setStyles] = useState<StylePreset[]>([]);
  const [title, setTitle] = useState("");
  const [shots, setShots] = useState<
    Array<{ shot_id: number; start_s: number; duration_s: number; text: string }>
  >([]);
  const [styleId, setStyleId] = useState("tiktok_karaoke");
  const [ratio, setRatio] = useState<"9:16" | "16:9" | "1:1">("9:16");
  const [voiceLang, setVoiceLang] = useState<"none" | "vi" | "en">("vi");
  const [ttsAudioUrl, setTtsAudioUrl] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await apiFetch<{ video: VideoDetail }>(`/api/v1/videos/${videoId}`);
      const v = res.video;
      setVideo(v);
      setTitle(v.plan?.title || "");
      setShots(v.plan?.shots || []);
      setStyleId(v.style_preset || "tiktok_karaoke");
      setRatio(v.aspect_ratio || "9:16");
      setVoiceLang(v.voice_lang || "vi");

      const st = await apiFetch<{ styles: StylePreset[] }>(
        `/api/v1/styles?workspace_id=${v.workspace_id}`
      );
      setStyles(st.styles || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Không tải được chi tiết video");
    }
  }, [videoId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSavePlan = async () => {
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ video: VideoDetail }>(`/api/v1/videos/${videoId}`, {
        method: "PATCH",
        body: JSON.stringify({
          title,
          shots,
          style_preset: styleId,
          aspect_ratio: ratio,
          voice_lang: voiceLang,
        }),
      });
      setVideo(res.video);
      setMsg("Đã lưu kịch bản và cập nhật ngân sách âm tiết.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi lưu kịch bản");
    }
  };

  const handlePreviewVoice = async (text: string) => {
    setErr("");
    try {
      const data = await apiFetch<{ audio_url: string; duration_s: number }>(
        "/api/v1/voices/preview",
        {
          method: "POST",
          body: JSON.stringify({
            text,
            lang: voiceLang === "en" ? "en" : "vi",
          }),
        }
      );
      setTtsAudioUrl(data.audio_url);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Không thể đọc thử giọng TTS");
    }
  };

  const handleRender = async () => {
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ job_id?: number; mode: string }>(
        `/api/v1/videos/${videoId}/render`,
        { method: "POST", body: JSON.stringify({ sync: false }) }
      );
      setMsg(`Đã gửi job dựng video vào làn Compute (Job #${res.job_id}).`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Không thể dựng video");
    }
  };

  const handleRestyle = async () => {
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ job_id?: number; mode: string }>(
        `/api/v1/videos/${videoId}/restyle`,
        { method: "POST", body: JSON.stringify({ style_preset: styleId, sync: false }) }
      );
      setMsg(`Đã xếp hàng đợi đổi Style sang "${styleId}" (Job #${res.job_id}).`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Không thể đổi style");
    }
  };

  if (!video) {
    return (
      <div className="max-w-5xl mx-auto text-sm text-slate-400">
        {err || "Đang tải chi tiết video..."}
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Link
            href="/videos"
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-xl font-bold text-white">
              Video #{video.id} — {video.plan?.title || "Biên tập"}
            </h1>
            <div className="text-xs text-slate-400">
              Trạng thái: <strong className="text-sky-300">{video.status}</strong> •{" "}
              {video.duration_s ? `${video.duration_s.toFixed(1)}s` : "Chưa xuất MP4"}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2 text-xs">
          <button
            onClick={() => void handleSavePlan()}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-white border border-slate-700 cursor-pointer"
          >
            <Save className="w-3.5 h-3.5" /> Lưu Kịch bản
          </button>
          <button
            onClick={() => void handleRender()}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
          >
            <Play className="w-3.5 h-3.5" /> Dựng Video
          </button>
          <button
            onClick={() => void handleRestyle()}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-purple-500/20 hover:bg-purple-500/30 text-purple-200 border border-purple-500/40 cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Đổi Style Nhanh
          </button>
          {video.output_url && (
            <a
              href={`/api/v1/videos/${video.id}/publish-pack`}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
            >
              <Download className="w-3.5 h-3.5" /> Tải Gói .zip
            </a>
          )}
        </div>
      </div>

      {msg && (
        <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs rounded-lg px-4 py-2.5">
          {msg}
        </div>
      )}
      {err && (
        <div className="bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs rounded-lg px-4 py-2.5">
          {err}
        </div>
      )}

      <div className="grid md:grid-cols-5 gap-6">
        {/* Script & Style Controls */}
        <div className="md:col-span-3 bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-4 text-xs">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-slate-400 block mb-1">Tiêu đề</label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              />
            </div>
            <div>
              <label className="text-slate-400 block mb-1">Style Preset</label>
              <select
                value={styleId}
                onChange={(e) => setStyleId(e.target.value)}
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              >
                {styles.map((st) => (
                  <option key={st.id} value={st.id}>
                    {st.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-slate-400 block mb-1">Khung hình & Voice</label>
              <div className="flex gap-1.5">
                <select
                  value={ratio}
                  onChange={(e) => setRatio(e.target.value as "9:16" | "16:9" | "1:1")}
                  className="flex-1 bg-[#182235] border border-slate-700 rounded-lg px-2 py-2"
                >
                  <option value="9:16">9:16</option>
                  <option value="16:9">16:9</option>
                  <option value="1:1">1:1</option>
                </select>
                <select
                  value={voiceLang}
                  onChange={(e) => setVoiceLang(e.target.value as "none" | "vi" | "en")}
                  className="flex-1 bg-[#182235] border border-slate-700 rounded-lg px-2 py-2"
                >
                  <option value="vi">VI</option>
                  <option value="en">EN</option>
                  <option value="none">Mute</option>
                </select>
              </div>
            </div>
          </div>

          <div className="space-y-3">
            <div className="font-semibold text-white">Lời thoại từng cảnh & Ngân sách âm tiết</div>
            {shots.map((shot, idx) => {
              const budget = video.syllable_budget?.[idx];
              return (
                <div
                  key={idx}
                  className="bg-[#182235] border border-slate-700/70 rounded-lg p-3 space-y-2"
                >
                  <div className="flex items-center justify-between text-[11px] text-slate-400">
                    <span>
                      Cảnh #{idx + 1} (Shot #{shot.shot_id}, {shot.duration_s}s)
                    </span>
                    <div className="flex items-center gap-3">
                      {budget && (
                        <span
                          className={
                            budget.over_budget ? "text-amber-300 font-semibold" : "text-emerald-300"
                          }
                        >
                          {budget.syllables}/{budget.max_syllables} âm tiết
                        </span>
                      )}
                      {shot.text && (
                        <button
                          type="button"
                          onClick={() => void handlePreviewVoice(shot.text)}
                          className="inline-flex items-center gap-1 text-sky-400 hover:underline cursor-pointer"
                        >
                          <Volume2 className="w-3 h-3" /> Nghe thử TTS
                        </button>
                      )}
                    </div>
                  </div>
                  <textarea
                    rows={2}
                    value={shot.text}
                    onChange={(e) => {
                      const val = e.target.value;
                      setShots((prev) =>
                        prev.map((s, i) => (i === idx ? { ...s, text: val } : s))
                      );
                    }}
                    className="w-full bg-[#0b0f17] border border-slate-700 rounded px-2.5 py-1.5 text-slate-100"
                  />
                </div>
              );
            })}
            {ttsAudioUrl && (
              <div className="pt-2">
                <div className="text-[11px] text-slate-400 mb-1">Âm thanh nghe thử TTS:</div>
                <audio controls src={ttsAudioUrl} className="w-full h-8" />
              </div>
            )}
          </div>
        </div>

        {/* Video Preview & QC Report */}
        <div className="md:col-span-2 bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-4 text-xs">
          <div className="font-semibold text-sm text-white">Xem thử Thành phẩm & QC</div>
          {video.output_url ? (
            <video
              controls
              src={video.output_url}
              className="w-full max-h-96 rounded-lg bg-black border border-slate-800"
            />
          ) : (
            <div className="h-56 rounded-lg bg-[#182235] border border-slate-800 flex items-center justify-center text-slate-500">
              Chưa có file render. Bấm &ldquo;Dựng Video&rdquo;.
            </div>
          )}

          <div className="bg-[#182235] border border-slate-700/70 rounded-lg p-3 space-y-1.5">
            <div className="font-semibold text-white">Báo cáo QC FFmpeg</div>
            {video.qc?.passed === undefined ? (
              <div className="text-slate-400">Chưa chạy kiểm tra QC.</div>
            ) : (
              <>
                <div className={video.qc.passed ? "text-emerald-300" : "text-rose-300"}>
                  {video.qc.passed ? "✓ Đạt toàn bộ kiểm tra" : "✗ Phát hiện lỗi kỹ thuật"}
                </div>
                {video.qc.integrated_lufs !== undefined && video.qc.integrated_lufs !== null && (
                  <div className="text-slate-400">
                    Độ lớn trung bình: {video.qc.integrated_lufs.toFixed(1)} LUFS
                  </div>
                )}
                {video.qc.issues?.map((issue, i) => (
                  <div key={i} className="text-rose-300">
                    • {issue}
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
