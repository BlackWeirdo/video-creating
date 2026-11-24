"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Languages, Play, Scissors, Upload } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";
import { SimulationBadge } from "@/components/SimulationBadge";

interface LocalizeSegment {
  index: number;
  start_s: number;
  end_s: number;
  source_text: string;
  translated_text: string;
  syllable_count?: number;
  syllable_budget?: number;
  replace_shot_id: number;
}

interface LocalizeProject {
  id: number;
  title: string;
  mode: "reup_vi" | "hybrid_remix" | "intl_export";
  source_lang: string;
  target_lang: string;
  hardsub_mode: "none" | "blur_bar" | "crop_frame" | "ocr_inpaint";
  style_preset: string;
  aspect_ratio: string;
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

export default function LocalizePage() {
  const { activeWorkspaceId, activeWorkspace } = useWorkspace();
  const [projects, setProjects] = useState<LocalizeProject[]>([]);
  const [shots, setShots] = useState<ShotRow[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const [title, setTitle] = useState("");
  const [mode, setMode] = useState<"reup_vi" | "hybrid_remix" | "intl_export">("intl_export");
  const [sourceMediaPath, setSourceMediaPath] = useState("");
  const [targetLang, setTargetLang] = useState("vi");
  const [hardsubMode, setHardsubMode] = useState<"none" | "blur_bar" | "crop_frame" | "ocr_inpaint">("blur_bar");
  const [stylePreset, setStylePreset] = useState("tiktok_karaoke");
  const [mirror, setMirror] = useState(false);

  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    const policy = activeWorkspace?.content_policy;
    if (policy === "strict_footage") setMode("intl_export");
    else if (policy === "hybrid_remix") setMode("hybrid_remix");
    else if (policy === "full_ai") setMode("reup_vi");
  }, [activeWorkspace?.content_policy]);

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
          target_lang: targetLang,
          hardsub_mode: hardsubMode,
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
        { method: "POST", body: JSON.stringify({ sync: false }) }
      );
      setMsg(
        action === "extract"
          ? `Đã xếp hàng tách nhạc/giọng & chép lời (Job #${res.job_id}).`
          : `Đã xếp hàng render Việt hóa / Remix (Job #${res.job_id}).`
      );
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi thực thi");
    }
  };

  const activeProj = projects.find((p) => p.id === selectedId) || projects[0] || null;

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

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Languages className="w-6 h-6 text-sky-400" /> Studio Việt hóa, Hybrid Remix & Quốc tế hóa
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Chính sách Workspace hiện tại:{" "}
          <span className="text-sky-300 font-semibold">
            {activeWorkspace?.content_policy || "strict_footage"}
          </span>{" "}
          — Tách nhạc/lời, xử lý chữ cứng 3 chế độ (che mờ, crop khung, OCR Inpaint) & tráo shot thật.
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
        <h2 className="text-sm font-semibold text-white">Tạo Dự Án Localize / Remix Mới</h2>
        <div className="grid md:grid-cols-4 gap-3">
          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Tên dự án (VD: Việt hóa video review bạc)"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as LocalizeProject["mode"])}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="reup_vi" disabled={activeWorkspace?.content_policy !== "full_ai"}>
              Việt hóa Reup (Full AI)
            </option>
            <option
              value="hybrid_remix"
              disabled={activeWorkspace?.content_policy === "strict_footage"}
            >
              Hybrid Remix (Tráo shot thật)
            </option>
            <option value="intl_export">Quốc tế hóa ngược (EN/ZH/JA/KO)</option>
          </select>
          <select
            value={hardsubMode}
            onChange={(e) => setHardsubMode(e.target.value as LocalizeProject["hardsub_mode"])}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="blur_bar">Che dải mờ (Blur Bar)</option>
            <option value="crop_frame">Crop khung mất chữ</option>
            <option value="ocr_inpaint">OCR + Delogo/Inpaint xóa chữ</option>
            <option value="none">Giữ nguyên khung hình</option>
          </select>
          <select
            value={targetLang}
            onChange={(e) => setTargetLang(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="vi">Tiếng Việt (vi)</option>
            <option value="en">English (en)</option>
            <option value="zh">中文 (zh)</option>
            <option value="ja">日本語 (ja)</option>
            <option value="ko">한국어 (ko)</option>
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
          <div className="flex items-center justify-between gap-2">
            <select
              value={stylePreset}
              onChange={(e) => setStylePreset(e.target.value)}
              className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2 flex-1"
            >
              <option value="tiktok_karaoke">TikTok Karaoke</option>
              <option value="bilingual_stack">Song ngữ (Bilingual)</option>
              <option value="box_highlight">Hộp nổi bật</option>
              <option value="neon_glow">Neon Glow</option>
            </select>
            <label className="flex items-center gap-1.5 text-slate-300">
              <input
                type="checkbox"
                checked={mirror}
                onChange={(e) => setMirror(e.target.checked)}
              />
              Lật gương
            </label>
          </div>
        </div>

        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
        >
          Tạo Dự Án
        </button>
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
                {p.mode} → {p.target_lang} • {p.hardsub_mode}
              </div>
              <div className="flex gap-2 pt-1">
                <button
                  type="button"
                  onClick={(ev) => {
                    ev.stopPropagation();
                    void runAction(p.id, "extract");
                  }}
                  className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-amber-300 cursor-pointer"
                >
                  <Scissors className="w-3 h-3 inline mr-1" /> Tách lời & Dịch
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

        <div className="lg:col-span-2 bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3">
          <h3 className="font-semibold text-white">
            Biên tập Đoạn thoại & Tráo Shot thật {activeProj ? `— #${activeProj.id}` : ""}
          </h3>
          {activeProj && <SimulationBadge flags={activeProj.simulation_flags} />}
          {!activeProj || activeProj.segments.length === 0 ? (
            <div className="text-slate-500 py-6 text-center">
              Chọn dự án và bấm &quot;Tách lời &amp; Dịch&quot; để sinh các đoạn lời theo nhịp giây.
            </div>
          ) : (
            <div className="space-y-2.5">
              {activeProj.segments.map((seg, idx) => (
                <div
                  key={idx}
                  className="bg-[#182235] border border-slate-700/70 rounded-lg p-3 space-y-2"
                >
                  <div className="flex justify-between text-[11px] text-slate-400">
                    <span>
                      Đoạn #{idx + 1}: {seg.start_s.toFixed(1)}s – {seg.end_s.toFixed(1)}s
                    </span>
                    <span>
                      Âm tiết: {seg.syllable_count ?? "?"}/{seg.syllable_budget ?? "?"}
                    </span>
                  </div>
                  <div className="text-[11px] text-slate-400">Gốc: {seg.source_text}</div>
                  <input
                    defaultValue={seg.translated_text}
                    onBlur={(e) =>
                      void updateSegField(activeProj, idx, { translated_text: e.target.value })
                    }
                    className="w-full bg-[#0b0f17] border border-slate-700 rounded px-2.5 py-1.5 text-slate-100"
                  />
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
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
