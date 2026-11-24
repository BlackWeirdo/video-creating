"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AudioWaveform, Play, Plus, Upload } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";
import { JobProgressBanner, useJobProgress } from "@/components/JobProgressBanner";
import { SimulationBadge } from "@/components/SimulationBadge";

interface CharacterOption {
  id: number;
  name: string;
}

interface LipsyncProject {
  id: number;
  title: string;
  character_id: number | null;
  portrait_path: string;
  aspect_ratio: string;
  engine_used: string;
  status: string;
  output_path: string;
  video_url: string;
  metrics?: { peak_rms?: number; active_speech_ratio?: number; frames?: number };
  simulation_flags?: string[];
}

export default function LipsyncStudioPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [projects, setProjects] = useState<LipsyncProject[]>([]);
  const [characters, setCharacters] = useState<CharacterOption[]>([]);
  const [title, setTitle] = useState("");
  const [characterId, setCharacterId] = useState("");
  const [aspectRatio, setAspectRatio] = useState("9:16");
  const [scriptText, setScriptText] = useState("");
  const [renderingId, setRenderingId] = useState<number | null>(null);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [lpRes, chRes] = await Promise.all([
        apiFetch<{ projects: LipsyncProject[] }>(
          `/api/v1/lipsync/projects?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ characters: CharacterOption[] }>(
          `/api/v1/characters?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      setProjects(lpRes.projects || []);
      setCharacters(chRes.characters || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Studio Lip-sync");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const { job: activeJob, isRunning: jobRunning } = useJobProgress(activeJobId, {
    onCompleted: () => {
      setMsg(`Đã render xong video Lip-sync #${renderingId ?? ""}.`);
      setRenderingId(null);
      void load();
    },
    onFailed: (j) => {
      setErr(j.error || "Lỗi dựng Lip-sync");
      setRenderingId(null);
      void load();
    },
  });

  const createProject = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ project: LipsyncProject }>("/api/v1/lipsync/projects", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          title: title || "Lip-sync MC Ảo",
          character_id: characterId ? Number(characterId) : null,
          aspect_ratio: aspectRatio,
          script_text: scriptText,
        }),
      });
      setTitle("");
      setScriptText("");
      setMsg(`Đã tạo dự án Lip-sync #${res.project.id}.`);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo dự án Lip-sync");
    }
  };

  const uploadPortrait = async (pid: number, file: File | null) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    await apiFetch(`/api/v1/lipsync/projects/${pid}/upload-portrait`, {
      method: "POST",
      body: fd,
    });
    setMsg(`Đã tải ảnh chân dung cho dự án #${pid}.`);
    await load();
  };

  const renderProject = async (pid: number) => {
    setRenderingId(pid);
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ job_id: number }>(`/api/v1/lipsync/projects/${pid}/render`, {
        method: "POST",
        body: JSON.stringify({ sync: false }),
      });
      setActiveJobId(res.job_id);
      setMsg(`Đã xếp hàng dựng Lip-sync #${pid} (Job #${res.job_id}).`);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi dựng Lip-sync");
      setRenderingId(null);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <AudioWaveform className="w-6 h-6 text-rose-400" /> Studio Lip-sync Nhân vật AI
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Kết hợp ảnh chân dung hoặc Nhân vật Cố định với giọng đọc / file thu âm, đồng bộ biên độ khẩu hình tự động.
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
      <JobProgressBanner
        job={activeJob}
        jobId={activeJobId}
        label={renderingId ? `Lip-sync #${renderingId}` : "Lip-sync Studio"}
        onDismiss={() => setActiveJobId(null)}
      />

      <form
        onSubmit={createProject}
        className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs"
      >
        <div className="grid md:grid-cols-3 gap-3">
          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Tiêu đề clip Lip-sync"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <select
            value={characterId}
            onChange={(e) => setCharacterId(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="">Tạo khung chân dung mặc định (hoặc tải ảnh)</option>
            {characters.map((ch) => (
              <option key={ch.id} value={ch.id}>
                Nhân vật: {ch.name}
              </option>
            ))}
          </select>
          <select
            value={aspectRatio}
            onChange={(e) => setAspectRatio(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="9:16">9:16 Dọc</option>
            <option value="16:9">16:9 Ngang</option>
            <option value="1:1">1:1 Vuông</option>
          </select>
        </div>
        <textarea
          required
          rows={3}
          value={scriptText}
          onChange={(e) => setScriptText(e.target.value)}
          placeholder="Nhập lời thoại MC sẽ nói trong video..."
          className="w-full bg-[#182235] border border-slate-700 rounded-lg p-3"
        />
        <button
          type="submit"
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-rose-500 hover:bg-rose-400 text-slate-950 font-semibold cursor-pointer"
        >
          <Plus className="w-4 h-4" /> Tạo Dự án Lip-sync
        </button>
      </form>

      <div className="grid md:grid-cols-2 gap-4">
        {projects.map((p) => (
          <div
            key={p.id}
            className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3 text-xs"
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-semibold text-white text-sm">{p.title}</div>
                <div className="text-[11px] text-slate-400">
                  Engine: {p.engine_used} • {p.aspect_ratio} •{" "}
                  <span className="text-sky-300">{p.status}</span>
                  {p.metrics?.peak_rms ? ` • RMS=${p.metrics.peak_rms}` : ""}
                </div>
              </div>
              <div className="flex gap-1.5">
                <label className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 cursor-pointer">
                  <Upload className="w-3.5 h-3.5" /> Ảnh
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    className="hidden"
                    onChange={(e) => void uploadPortrait(p.id, e.target.files?.[0] || null)}
                  />
                </label>
                <button
                  type="button"
                  disabled={jobRunning && renderingId === p.id}
                  onClick={() => void renderProject(p.id)}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold cursor-pointer disabled:opacity-50"
                >
                  <Play className="w-3.5 h-3.5" />{" "}
                  {jobRunning && renderingId === p.id ? "Đang dựng..." : "Render"}
                </button>
              </div>
            </div>
            {p.video_url && (
              <video
                controls
                preload="metadata"
                src={p.video_url}
                className="w-full max-h-56 rounded bg-black"
              />
            )}
            <SimulationBadge flags={p.simulation_flags} />
          </div>
        ))}
      </div>
    </div>
  );
}
