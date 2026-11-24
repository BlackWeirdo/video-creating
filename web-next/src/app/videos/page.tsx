"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Clapperboard, Plus } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";

interface ShotOption {
  id: number;
  start_s: number;
  end_s: number;
  description: string;
}

interface StyleOption {
  id: string;
  name: string;
  subtitle_style: string;
}

interface VideoSummary {
  id: number;
  status: string;
  aspect_ratio: string;
  style_preset: string;
  voice_lang: string;
  duration_s: number | null;
  plan: { title?: string; shots?: Array<Record<string, unknown>> };
  qc: { passed?: boolean };
  cover_url: string | null;
  output_url: string | null;
}

export default function VideosPage() {
  const { activeWorkspaceId, activeWorkspace } = useWorkspace();
  const [videos, setVideos] = useState<VideoSummary[]>([]);
  const [shots, setShots] = useState<ShotOption[]>([]);
  const [styles, setStyles] = useState<StyleOption[]>([]);
  const [title, setTitle] = useState("");
  const [selectedShotId, setSelectedShotId] = useState<number>(0);
  const [lineText, setLineText] = useState("");
  const [styleId, setStyleId] = useState("tiktok_karaoke");
  const [ratio, setRatio] = useState<"9:16" | "16:9" | "1:1">("9:16");
  const [voiceLang, setVoiceLang] = useState<"none" | "vi" | "en">("vi");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [vRes, sRes, stRes] = await Promise.all([
        apiFetch<{ videos: VideoSummary[] }>(`/api/v1/videos?workspace_id=${activeWorkspaceId}`),
        apiFetch<{ shots: ShotOption[] }>(`/api/v1/shots?workspace_id=${activeWorkspaceId}`),
        apiFetch<{ styles: StyleOption[] }>(`/api/v1/styles?workspace_id=${activeWorkspaceId}`),
      ]);
      setVideos(vRes.videos || []);
      setShots(sRes.shots || []);
      setStyles(stRes.styles || []);
      if (sRes.shots?.length && selectedShotId === 0) {
        setSelectedShotId(sRes.shots[0].id);
      }
      if (activeWorkspace?.default_aspect_ratio) {
        setRatio(activeWorkspace.default_aspect_ratio);
      }
      if (activeWorkspace?.style_preset) {
        setStyleId(activeWorkspace.style_preset);
      }
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải danh sách video");
    }
  }, [activeWorkspaceId, activeWorkspace, selectedShotId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    try {
      const shotObj = shots.find((s) => s.id === selectedShotId);
      const startS = shotObj ? shotObj.start_s : 0.0;
      const durS = shotObj ? Math.max(1.5, Math.min(5.0, shotObj.end_s - shotObj.start_s)) : 3.0;
      await apiFetch("/api/v1/videos", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          style_preset: styleId,
          aspect_ratio: ratio,
          voice_lang: voiceLang,
          plan: {
            title: title || "Video mới",
            shots: selectedShotId
              ? [{ shot_id: selectedShotId, start_s: startS, duration_s: durS, text: lineText }]
              : [],
          },
        }),
      });
      setTitle("");
      setLineText("");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo video");
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Clapperboard className="w-6 h-6 text-sky-400" /> Sản xuất & Kịch bản Video
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Lập kế hoạch video, biên tập lời thoại kèm đồng hồ âm tiết, dựng FFmpeg + đổi Style nhanh.
        </p>
      </div>

      {err && (
        <div className="bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs rounded-lg px-4 py-2.5">
          {err}
        </div>
      )}

      <form
        onSubmit={handleCreate}
        className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-4 text-xs"
      >
        <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
          <Plus className="w-4 h-4 text-sky-400" /> Lập Plan Video Mới
        </h2>
        <div className="grid md:grid-cols-4 gap-3">
          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Tiêu đề video..."
            className="md:col-span-2 bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <select
            value={styleId}
            onChange={(e) => setStyleId(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            {styles.map((st) => (
              <option key={st.id} value={st.id}>
                {st.name}
              </option>
            ))}
          </select>
          <select
            value={ratio}
            onChange={(e) => setRatio(e.target.value as "9:16" | "16:9" | "1:1")}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="9:16">9:16 Dọc</option>
            <option value="16:9">16:9 Ngang</option>
            <option value="1:1">1:1 Vuông</option>
          </select>
        </div>
        <div className="grid md:grid-cols-3 gap-3">
          <select
            value={selectedShotId}
            onChange={(e) => setSelectedShotId(Number(e.target.value))}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value={0}>-- Chọn Shot đầu tiên --</option>
            {shots.map((s) => (
              <option key={s.id} value={s.id}>
                Shot #{s.id}: {s.description || `${s.start_s}s-${s.end_s}s`}
              </option>
            ))}
          </select>
          <select
            value={voiceLang}
            onChange={(e) => setVoiceLang(e.target.value as "none" | "vi" | "en")}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="vi">Giọng đọc Tiếng Việt</option>
            <option value="en">Giọng đọc English</option>
            <option value="none">Không lồng tiếng (chỉ nhạc/gốc)</option>
          </select>
          <input
            value={lineText}
            onChange={(e) => setLineText(e.target.value)}
            placeholder="Lời bình / phụ đề cho cảnh..."
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
        </div>
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
        >
          Tạo Video Plan
        </button>
      </form>

      <div className="grid md:grid-cols-3 gap-4">
        {videos.map((v) => (
          <Link
            key={v.id}
            href={`/videos/${v.id}`}
            className="bg-[#111827] border border-slate-800 hover:border-sky-500/40 rounded-xl p-4 space-y-2.5 transition-colors block text-xs"
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-white truncate">
                #{v.id} — {v.plan?.title || "Chưa đặt tiêu đề"}
              </span>
              <span className="px-2 py-0.5 rounded bg-slate-800 text-sky-300 text-[10px]">
                {v.status}
              </span>
            </div>
            <div className="text-slate-400">
              Style: <strong className="text-slate-200">{v.style_preset}</strong> •{" "}
              {v.aspect_ratio} • {v.duration_s ? `${v.duration_s.toFixed(1)}s` : "Chưa dựng"}
            </div>
            {v.qc?.passed === true && (
              <div className="text-[11px] text-emerald-400">✓ QC FFmpeg Đạt chuẩn</div>
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}
