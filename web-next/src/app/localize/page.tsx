"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Eye, Languages, Play, Scissors, Upload, Users, Volume2 } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";
import { SimulationBadge } from "@/components/SimulationBadge";

interface LocalizeSegment {
  index: number;
  start_s: number;
  end_s: number;
  source_text: string;
  translated_text: string;
  speaker_id?: string;
  text_origin?: string;
  syllable_count?: number;
  syllable_budget?: number;
  replace_shot_id: number;
  preview_audio_url?: string;
}

interface SpeakerEntry {
  label: string;
  provider: string;
  voice_id: string;
  ref_audio_rel?: string;
}

interface OcrCue {
  start_s: number;
  end_s: number;
  text: string;
  confidence: number;
  box: { x: number; y: number; w: number; h: number };
}

interface LocalizeProject {
  id: number;
  title: string;
  mode: "reup_vi" | "hybrid_remix" | "intl_export";
  source_lang: string;
  target_lang: string;
  hardsub_mode: "none" | "blur_bar" | "crop_frame" | "ocr_inpaint";
  hardsub_box: { x: number; y: number; w: number; h: number };
  style_preset: string;
  aspect_ratio: string;
  whisper_size?: "small" | "medium";
  translation_style?: "natural_tiktok" | "literal";
  clone_source_voice?: boolean;
  clone_consent_confirmed?: boolean;
  speaker_config?: { speakers?: Record<string, SpeakerEntry>; trans_engine?: string };
  ocr_cues?: OcrCue[];
  status: string;
  output_video_id: number | null;
  error: string | null;
  segments: LocalizeSegment[];
  simulation_flags?: string[];
}

interface ShotRow {
  id: number;
  description: string;
  has_product: number;
}

const SPEAKER_VOICE_OPTIONS = [
  { provider: "edge", voice_id: "vi-VN-HoaiMyNeural", label: "Edge TTS: Hoài My (Nữ)" },
  { provider: "edge", voice_id: "vi-VN-NamMinhNeural", label: "Edge TTS: Nam Minh (Nam)" },
  { provider: "vieneu", voice_id: "Trúc Ly", label: "VieNeu CPU: Trúc Ly (Nữ Bắc)" },
  { provider: "vieneu", voice_id: "Minh Quân", label: "VieNeu CPU: Minh Quân (Nam Bắc)" },
  { provider: "vieneu", voice_id: "Ái Hân", label: "VieNeu CPU: Ái Hân (Nữ Nam)" },
  { provider: "vieneu", voice_id: "Adam", label: "VieNeu CPU: Adam (Nam Nam)" },
  { provider: "vieneu", voice_id: "Mỹ Duyên", label: "VieNeu CPU: Mỹ Duyên (Kể chuyện)" },
  { provider: "vieneu", voice_id: "Đức Trí", label: "VieNeu CPU: Đức Trí (Đọc truyện)" },
  { provider: "edge", voice_id: "en-US-JennyNeural", label: "Edge TTS: Jenny (EN)" },
  { provider: "edge", voice_id: "en-US-GuyNeural", label: "Edge TTS: Guy (EN)" },
];

export default function LocalizePage() {
  const { activeWorkspaceId, activeWorkspace } = useWorkspace();
  const [projects, setProjects] = useState<LocalizeProject[]>([]);
  const [shots, setShots] = useState<ShotRow[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const [title, setTitle] = useState("");
  const [mode, setMode] = useState<"reup_vi" | "hybrid_remix" | "intl_export">("intl_export");
  const [sourceMediaPath, setSourceMediaPath] = useState("");
  const [sourceLang, setSourceLang] = useState("auto");
  const [targetLang, setTargetLang] = useState("vi");
  const [hardsubMode, setHardsubMode] = useState<"none" | "blur_bar" | "crop_frame" | "ocr_inpaint">("blur_bar");
  const [whisperSize, setWhisperSize] = useState<"small" | "medium">("small");
  const [translationStyle, setTranslationStyle] = useState<"natural_tiktok" | "literal">("natural_tiktok");
  const [stylePreset, setStylePreset] = useState("tiktok_karaoke");
  const [mirror, setMirror] = useState(false);

  const [previewAudioMap, setPreviewAudioMap] = useState<Record<string, string>>({});
  const [previewLoadingKey, setPreviewLoadingKey] = useState<string | null>(null);
  const [showBoxPreview, setShowBoxPreview] = useState(false);
  const [cloneModalOpen, setCloneModalOpen] = useState(false);

  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const wsPolicy = activeWorkspace?.content_policy || "strict_footage";
  const canCloneVoice = wsPolicy === "hybrid_remix" || wsPolicy === "full_ai";

  useEffect(() => {
    if (wsPolicy === "strict_footage") setMode("intl_export");
    else if (wsPolicy === "hybrid_remix") setMode("hybrid_remix");
    else if (wsPolicy === "full_ai") setMode("reup_vi");
  }, [wsPolicy]);

  const load = useCallback(async () => {
    try {
      const [pRes, sRes] = await Promise.all([
        apiFetch<{ projects: LocalizeProject[] }>(
          `/api/v1/localize/projects?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ shots: ShotRow[] }>(
          `/api/v1/shots?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      const list = pRes.projects || [];
      setProjects(list);
      setShots(sRes.shots || []);
      if (list.length > 0 && selectedId === null) {
        setSelectedId(list[0].id);
      }
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Localize Studio");
    }
  }, [activeWorkspaceId, selectedId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setErr("");
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch("/api/v1/localize/upload", { method: "POST", body: fd });
    const data = await resp.json();
    if (!resp.ok) {
      setErr(data.detail || "Tải video thất bại");
      return;
    }
    setSourceMediaPath(data.source_media_path || "");
    setMsg(`Đã tải video nguồn: ${data.source_media_path}`);
  };

  const createProject = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ project: LocalizeProject }>("/api/v1/localize/projects", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          title,
          mode,
          source_media_path: sourceMediaPath,
          source_lang: sourceLang,
          target_lang: targetLang,
          hardsub_mode: hardsubMode,
          whisper_size: whisperSize,
          translation_style: translationStyle,
          style_preset: stylePreset,
          anti_dup: { mirror, zoom: 1.04, color_eq: true },
        }),
      });
      setTitle("");
      setSelectedId(res.project.id);
      setMsg(`Đã tạo dự án Việt hóa / Remix #${res.project.id}.`);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo dự án");
    }
  };

  const runAction = async (id: number, action: "extract" | "render") => {
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ job_id: number | null }>(
        `/api/v1/localize/projects/${id}/${action}`,
        { method: "POST", body: JSON.stringify({ sync: false, tts_provider: "auto" }) }
      );
      setMsg(
        action === "extract"
          ? `Đã xếp hàng tách nhạc MDX-Net, OCR chữ cứng, phân biệt người nói & dịch (Job #${res.job_id}).`
          : `Đã xếp hàng render Việt hóa / Remix (Job #${res.job_id}).`
      );
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi thực thi");
    }
  };

  const activeProj = projects.find((p) => p.id === selectedId) || projects[0] || null;
  const speakersMap: Record<string, SpeakerEntry> =
    activeProj?.speaker_config?.speakers || {
      SPK_1: { label: "Người nói 1", provider: "edge", voice_id: "vi-VN-HoaiMyNeural" },
    };
  const speakerIds = Object.keys(speakersMap).length > 0 ? Object.keys(speakersMap) : ["SPK_1"];

  const updateSegField = async (
    proj: LocalizeProject,
    segIdx: number,
    patch: Partial<LocalizeSegment>
  ) => {
    const nextSegs = (proj.segments || []).map((s, idx) =>
      idx === segIdx ? { ...s, ...patch } : s
    );
    await apiFetch(`/api/v1/localize/projects/${proj.id}`, {
      method: "PATCH",
      body: JSON.stringify({ segments: nextSegs }),
    });
    await load();
  };

  const updateSpeakerConfig = async (
    proj: LocalizeProject,
    spkId: string,
    patch: Partial<SpeakerEntry>
  ) => {
    const curSpeakers = { ...(proj.speaker_config?.speakers || {}) };
    curSpeakers[spkId] = { ...(curSpeakers[spkId] || { label: spkId, provider: "edge", voice_id: "vi-VN-HoaiMyNeural" }), ...patch };
    await apiFetch(`/api/v1/localize/projects/${proj.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        speaker_config: { ...(proj.speaker_config || {}), speakers: curSpeakers },
      }),
    });
    await load();
  };

  const handlePreviewLine = async (proj: LocalizeProject, segIdx: number) => {
    const key = `${proj.id}:${segIdx}`;
    setPreviewLoadingKey(key);
    setErr("");
    try {
      const res = await apiFetch<{ audio_url: string }>(
        `/api/v1/localize/projects/${proj.id}/preview-segment`,
        {
          method: "POST",
          body: JSON.stringify({ segment_index: segIdx, tts_provider: "auto" }),
        }
      );
      setPreviewAudioMap((prev) => ({ ...prev, [key]: `${res.audio_url}?t=${Date.now()}` }));
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo âm thanh nghe thử");
    } finally {
      setPreviewLoadingKey(null);
    }
  };

  const toggleCloneVoice = async (proj: LocalizeProject, wantEnable: boolean) => {
    if (!wantEnable) {
      await apiFetch(`/api/v1/localize/projects/${proj.id}`, {
        method: "PATCH",
        body: JSON.stringify({ clone_source_voice: false }),
      });
      await load();
      return;
    }
    setCloneModalOpen(true);
  };

  const confirmEnableClone = async () => {
    if (!activeProj) return;
    setErr("");
    try {
      await apiFetch(`/api/v1/localize/projects/${activeProj.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          clone_source_voice: true,
          clone_consent_confirmed: true,
        }),
      });
      setCloneModalOpen(false);
      setMsg("Đã bật nhân bản giọng người nói gốc (VieNeu-TTS v3 Nano, phạm vi nội bộ dự án).");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể bật nhân bản giọng");
      setCloneModalOpen(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Languages className="w-6 h-6 text-sky-400" /> Studio Việt hóa, Hybrid Remix &amp; Quốc tế hóa
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Chính sách Workspace:{" "}
          <span className="text-sky-300 font-semibold">{wsPolicy}</span> — Tách nhạc MDX-Net ONNX,
          OCR phụ đề Trung/Anh + Faster-Whisper, phân biệt nhiều người nói và nhân bản giọng VieNeu CPU.
        </p>
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

      <form
        onSubmit={createProject}
        className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs"
      >
        <h2 className="text-sm font-semibold text-white">Tạo Dự Án Việt hóa / Remix Mới</h2>
        <div className="grid md:grid-cols-4 gap-3">
          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Tên dự án (VD: Việt hóa Douyin trang sức)"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as LocalizeProject["mode"])}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="reup_vi" disabled={wsPolicy !== "full_ai"}>
              Việt hóa Reup (Full AI)
            </option>
            <option value="hybrid_remix" disabled={wsPolicy === "strict_footage"}>
              Hybrid Remix (Tráo shot thật)
            </option>
            <option value="intl_export">Quốc tế hóa ngược (EN/ZH/JA/KO)</option>
          </select>
          <select
            value={sourceLang}
            onChange={(e) => setSourceLang(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="auto">Nguồn: Tự nhận diện (Trung/Anh)</option>
            <option value="zh">Nguồn: Tiếng Trung (Douyin/XHS)</option>
            <option value="en">Nguồn: Tiếng Anh (TikTok/YT)</option>
            <option value="vi">Nguồn: Tiếng Việt</option>
          </select>
          <select
            value={targetLang}
            onChange={(e) => setTargetLang(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="vi">Đích: Tiếng Việt (vi)</option>
            <option value="en">Đích: English (en)</option>
            <option value="zh">Đích: 中文 (zh)</option>
            <option value="ja">Đích: 日本語 (ja)</option>
            <option value="ko">Đích: 한국어 (ko)</option>
          </select>
        </div>

        <div className="grid md:grid-cols-4 gap-3">
          <select
            value={hardsubMode}
            onChange={(e) => setHardsubMode(e.target.value as LocalizeProject["hardsub_mode"])}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="blur_bar">OCR dò chữ → Phủ dải mờ đúng vị trí (Mặc định)</option>
            <option value="ocr_inpaint">LaMa ONNX Inpaint xóa chữ (Chất lượng cao)</option>
            <option value="crop_frame">Crop khung mất chữ</option>
            <option value="none">Giữ nguyên khung hình</option>
          </select>
          <select
            value={translationStyle}
            onChange={(e) => setTranslationStyle(e.target.value as "natural_tiktok" | "literal")}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="natural_tiktok">Phiên dịch tự nhiên TikTok Việt (Khớp nhịp)</option>
            <option value="literal">Dịch sát nghĩa gốc</option>
          </select>
          <select
            value={whisperSize}
            onChange={(e) => setWhisperSize(e.target.value as "small" | "medium")}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="small">Whisper Small (Nhanh, mặc định CPU)</option>
            <option value="medium">Whisper Medium (Chính xác cao tiếng Trung)</option>
          </select>
          <select
            value={stylePreset}
            onChange={(e) => setStylePreset(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="tiktok_karaoke">Phụ đề TikTok Karaoke</option>
            <option value="bilingual_stack">Phụ đề Song ngữ</option>
            <option value="box_highlight">Hộp nổi bật</option>
            <option value="neon_glow">Neon Glow</option>
          </select>
        </div>

        <div className="grid md:grid-cols-3 gap-3 items-center">
          <input
            value={sourceMediaPath}
            onChange={(e) => setSourceMediaPath(e.target.value)}
            placeholder="Đường dẫn tương đối (vd: localize/uploads/...)"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <label className="inline-flex items-center gap-2 px-3 py-2 bg-[#182235] border border-slate-700 rounded-lg cursor-pointer hover:border-sky-400">
            <Upload className="w-4 h-4 text-sky-400" />
            <span>Tải video nguồn (.mp4)</span>
            <input type="file" accept=".mp4,.mov,.mkv,.webm" onChange={handleUpload} className="hidden" />
          </label>
          <div className="flex items-center justify-between gap-3">
            <label className="flex items-center gap-1.5 text-slate-300">
              <input
                type="checkbox"
                checked={mirror}
                onChange={(e) => setMirror(e.target.checked)}
              />
              Lật gương chống trùng
            </label>
            <button
              type="submit"
              className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
            >
              Tạo Dự Án
            </button>
          </div>
        </div>
      </form>

      <div className="grid lg:grid-cols-3 gap-4 text-xs">
        <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-2">
          <h3 className="font-semibold text-white">Danh sách Dự án ({projects.length})</h3>
          {projects.map((p) => (
            <div
              key={p.id}
              onClick={() => setSelectedId(p.id)}
              className={`p-3 rounded-lg border cursor-pointer space-y-1 ${
                activeProj?.id === p.id
                  ? "bg-sky-500/10 border-sky-500/40"
                  : "bg-[#182235] border-slate-800"
              }`}
            >
              <div className="flex justify-between font-medium text-white">
                <span>{p.title}</span>
                <span className="text-[11px] text-sky-300">{p.status}</span>
              </div>
              <div className="text-[11px] text-slate-400">
                {p.mode} → {p.target_lang} • {p.hardsub_mode} •{" "}
                {p.translation_style === "literal" ? "Sát nghĩa" : "Tự nhiên"}
              </div>
              <div className="flex flex-wrap gap-2 pt-1">
                <button
                  type="button"
                  onClick={(ev) => {
                    ev.stopPropagation();
                    void runAction(p.id, "extract");
                  }}
                  className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-amber-300 cursor-pointer"
                >
                  <Scissors className="w-3 h-3 inline mr-1" /> Tách lời &amp; Dịch
                </button>
                <button
                  type="button"
                  onClick={(ev) => {
                    ev.stopPropagation();
                    void runAction(p.id, "render");
                  }}
                  className="px-2 py-1 rounded bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 cursor-pointer"
                >
                  <Play className="w-3 h-3 inline mr-1" /> Render
                </button>
                {p.output_video_id && (
                  <Link href={`/videos/${p.output_video_id}`} className="text-sky-400 hover:underline self-center">
                    Video #{p.output_video_id}
                  </Link>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="lg:col-span-2 bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold text-white">
              Bảng Song Ngữ, Phân Vai Giọng Đọc &amp; Vùng Chữ Cứng{" "}
              {activeProj ? `— #${activeProj.id}` : ""}
            </h3>
            {activeProj && (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowBoxPreview((v) => !v)}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-sky-300 cursor-pointer"
                >
                  <Eye className="w-3.5 h-3.5" />{" "}
                  {showBoxPreview ? "Ẩn vùng che chữ" : `Xem vùng che chữ (${activeProj.ocr_cues?.length || 0} cue OCR)`}
                </button>
              </div>
            )}
          </div>

          {activeProj && <SimulationBadge flags={activeProj.simulation_flags} />}

          {/* Multi-speaker voice mapping & Original Voice Cloning Safeguard */}
          {activeProj && activeProj.segments.length > 0 && (
            <div className="bg-[#182235] border border-slate-800 rounded-lg p-3 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-semibold text-slate-200 flex items-center gap-1.5">
                  <Users className="w-4 h-4 text-purple-400" /> Phân vai Người nói ({speakerIds.length})
                </div>
                {canCloneVoice && activeProj.target_lang.startsWith("vi") && (
                  <label className="inline-flex items-center gap-1.5 text-[11px] text-amber-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={Boolean(activeProj.clone_source_voice)}
                      onChange={(e) => void toggleCloneVoice(activeProj, e.target.checked)}
                    />
                    Nhân bản giọng người nói gốc (VieNeu CPU)
                  </label>
                )}
              </div>

              <div className="grid md:grid-cols-2 gap-2">
                {speakerIds.map((spkId) => {
                  const spk = speakersMap[spkId] || {
                    label: spkId,
                    provider: "edge",
                    voice_id: "vi-VN-HoaiMyNeural",
                  };
                  return (
                    <div
                      key={spkId}
                      className="flex items-center gap-2 bg-[#0b0f17] border border-slate-800 rounded px-2.5 py-1.5"
                    >
                      <span className="text-[10px] font-mono text-purple-300 shrink-0">{spkId}</span>
                      <input
                        defaultValue={spk.label}
                        onBlur={(e) =>
                          void updateSpeakerConfig(activeProj, spkId, { label: e.target.value })
                        }
                        className="w-28 bg-[#182235] border border-slate-700 rounded px-2 py-1 text-[11px]"
                        title="Đổi nhãn hiển thị người nói"
                      />
                      <select
                        disabled={Boolean(activeProj.clone_source_voice)}
                        value={`${spk.provider}:${spk.voice_id}`}
                        onChange={(e) => {
                          const [prov, vid] = e.target.value.split(":");
                          void updateSpeakerConfig(activeProj, spkId, {
                            provider: prov,
                            voice_id: vid,
                          });
                        }}
                        className="flex-1 bg-[#182235] border border-slate-700 rounded px-2 py-1 text-[11px] disabled:opacity-50"
                      >
                        {SPEAKER_VOICE_OPTIONS.map((opt) => (
                          <option
                            key={`${opt.provider}:${opt.voice_id}`}
                            value={`${opt.provider}:${opt.voice_id}`}
                          >
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Hardsub Box Preview & Manual Fine-tune */}
          {activeProj && showBoxPreview && (
            <div className="bg-[#182235] border border-slate-700 rounded-lg p-3 flex flex-wrap gap-4 items-center">
              <div className="relative w-28 h-48 bg-slate-950 border border-slate-700 rounded overflow-hidden shrink-0">
                <div className="absolute inset-0 flex items-center justify-center text-[10px] text-slate-600">
                  Khung 9:16
                </div>
                <div
                  className="absolute border-2 border-amber-400 bg-amber-400/25"
                  style={{
                    left: `${Math.round((activeProj.hardsub_box?.x ?? 0.06) * 100)}%`,
                    top: `${Math.round((activeProj.hardsub_box?.y ?? 0.74) * 100)}%`,
                    width: `${Math.round((activeProj.hardsub_box?.w ?? 0.88) * 100)}%`,
                    height: `${Math.round((activeProj.hardsub_box?.h ?? 0.16) * 100)}%`,
                  }}
                />
              </div>
              <div className="flex-1 space-y-2 text-[11px]">
                <div className="font-semibold text-amber-300">
                  Vùng che / xóa phụ đề cứng (RapidOCR phát hiện {activeProj.ocr_cues?.length || 0} mốc chữ)
                </div>
                <p className="text-slate-400">
                  Khi có mốc OCR, hệ thống tự động che mờ hoặc chạy LaMa Inpaint đúng tọa độ từng câu theo thời gian; hộp dưới đây là vùng bao tổng quát.
                </p>
                <div className="grid grid-cols-4 gap-2">
                  {(["x", "y", "w", "h"] as const).map((k) => (
                    <label key={k} className="space-y-0.5">
                      <span className="text-slate-400 uppercase">{k}</span>
                      <input
                        type="number"
                        step="0.02"
                        min={0}
                        max={1}
                        defaultValue={activeProj.hardsub_box?.[k] ?? 0.1}
                        onBlur={(e) => {
                          const nextBox = {
                            ...(activeProj.hardsub_box || { x: 0.06, y: 0.74, w: 0.88, h: 0.16 }),
                            [k]: Number(e.target.value),
                          };
                          void apiFetch(`/api/v1/localize/projects/${activeProj.id}`, {
                            method: "PATCH",
                            body: JSON.stringify({ hardsub_box: nextBox }),
                          }).then(() => load());
                        }}
                        className="w-full bg-[#0b0f17] border border-slate-700 rounded px-2 py-1"
                      />
                    </label>
                  ))}
                </div>
              </div>
            </div>
          )}

          {!activeProj || activeProj.segments.length === 0 ? (
            <div className="text-slate-500 py-6 text-center">
              Chọn dự án và bấm &quot;Tách lời &amp; Dịch&quot; để chạy MDX-Net, OCR chữ cứng, Whisper &amp; dịch tự động.
            </div>
          ) : (
            <div className="space-y-2.5">
              {activeProj.segments.map((seg, idx) => {
                const pKey = `${activeProj.id}:${idx}`;
                const audioUrl = previewAudioMap[pKey] || seg.preview_audio_url;
                const overBudget =
                  (seg.syllable_count ?? 0) > Math.ceil((seg.syllable_budget ?? 99) * 1.25);
                return (
                  <div
                    key={idx}
                    className="bg-[#182235] border border-slate-700/70 rounded-lg p-3 space-y-2"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-400">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-slate-200">
                          #{idx + 1} ({seg.start_s.toFixed(1)}s – {seg.end_s.toFixed(1)}s)
                        </span>
                        {seg.text_origin && (
                          <span className="px-1.5 py-0.5 rounded bg-slate-800 text-sky-300 text-[10px] uppercase">
                            {seg.text_origin}
                          </span>
                        )}
                        <select
                          value={seg.speaker_id || "SPK_1"}
                          onChange={(e) =>
                            void updateSegField(activeProj, idx, { speaker_id: e.target.value })
                          }
                          className="bg-[#0b0f17] border border-slate-700 rounded px-2 py-0.5 text-purple-300"
                        >
                          {speakerIds.map((sid) => (
                            <option key={sid} value={sid}>
                              {speakersMap[sid]?.label || sid}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={overBudget ? "text-amber-300 font-semibold" : ""}>
                          Âm tiết: {seg.syllable_count ?? "?"}/{seg.syllable_budget ?? "?"}
                        </span>
                        <button
                          type="button"
                          disabled={previewLoadingKey === pKey}
                          onClick={() => void handlePreviewLine(activeProj, idx)}
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-sky-500/20 hover:bg-sky-500/30 text-sky-300 cursor-pointer disabled:opacity-50"
                        >
                          <Volume2 className="w-3 h-3" />{" "}
                          {previewLoadingKey === pKey ? "Đang đọc..." : "Nghe thử"}
                        </button>
                      </div>
                    </div>

                    <div className="text-[11px] text-slate-400">Gốc: {seg.source_text}</div>
                    <input
                      key={`${activeProj.id}-${idx}-${seg.translated_text}`}
                      defaultValue={seg.translated_text}
                      onBlur={(e) => {
                        if (e.target.value !== seg.translated_text) {
                          void updateSegField(activeProj, idx, { translated_text: e.target.value });
                        }
                      }}
                      className="w-full bg-[#0b0f17] border border-slate-700 rounded px-2.5 py-1.5 text-slate-100"
                    />
                    {audioUrl && (
                      <audio controls src={audioUrl} className="h-7 w-full max-w-sm" />
                    )}

                    {activeProj.mode === "hybrid_remix" && (
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className="text-amber-300">Tráo Shot thật:</span>
                        <select
                          value={seg.replace_shot_id || 0}
                          onChange={(e) =>
                            void updateSegField(activeProj, idx, {
                              replace_shot_id: Number(e.target.value),
                            })
                          }
                          className="bg-[#0b0f17] border border-slate-700 rounded px-2 py-1"
                        >
                          <option value={0}>Giữ hình gốc (đã xử lý hardsub)</option>
                          {shots.map((s) => (
                            <option key={s.id} value={s.id}>
                              Shot #{s.id} — {s.description || "Sản phẩm"}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Mandatory Responsibility Confirmation Modal for Source Voice Cloning (Decision 7c) */}
      {cloneModalOpen && activeProj && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
          <div className="bg-[#111827] border border-amber-500/40 rounded-xl max-w-md w-full p-5 space-y-4 text-xs">
            <div className="flex items-center gap-2 text-amber-300 font-bold text-sm">
              <AlertTriangle className="w-5 h-5 shrink-0" /> Xác nhận trách nhiệm Nhân bản Giọng gốc
            </div>
            <p className="text-slate-300 leading-relaxed">
              Nhân bản giọng người nói trong video gốc có thể ảnh hưởng đến quyền nhân thân / bản quyền và chính sách nội dung của TikTok, YouTube, Facebook.
            </p>
            <ul className="list-disc list-inside text-slate-400 space-y-1">
              <li>Mẫu giọng trích xuất chỉ lưu cục bộ trong dự án #{activeProj.id}, không đưa vào thư viện chung.</li>
              <li>Thao tác bật và xuất video được ghi nhận vào nhật ký kiểm toán (`audit_log`).</li>
              <li>Người vận hành chịu hoàn toàn trách nhiệm pháp lý và bản quyền khi đăng tải.</li>
            </ul>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setCloneModalOpen(false)}
                className="px-3 py-1.5 rounded-lg bg-slate-800 text-slate-300 cursor-pointer"
              >
                Huỷ bỏ
              </button>
              <button
                type="button"
                onClick={() => void confirmEnableClone()}
                className="px-3 py-1.5 rounded-lg bg-amber-500 text-slate-950 font-semibold cursor-pointer"
              >
                Tôi hiểu và chịu trách nhiệm — Bật nhân bản
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
