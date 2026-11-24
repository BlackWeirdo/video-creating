"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Mic, Play, Plus } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";
import { JobProgressBanner, useJobProgress } from "@/components/JobProgressBanner";
import { SimulationBadge } from "@/components/SimulationBadge";

interface PodcastProject {
  id: number;
  title: string;
  host_a_name: string;
  host_b_name: string;
  host_a_voice: string;
  host_b_voice: string;
  aspect_ratio: string;
  waveform_style: string;
  accent_color: string;
  status: string;
  output_video_id: number | null;
  output_path: string;
  video_url: string;
  simulation_flags?: string[];
}

interface ChannelVoiceOption {
  id: number;
  name: string;
  speaker_name: string;
  voice_token: string;
}

const BASE_PODCAST_VOICES = [
  { value: "vi-VN-HoaiMyNeural", label: "Edge TTS: Hoài My (Nữ)" },
  { value: "vi-VN-NamMinhNeural", label: "Edge TTS: Nam Minh (Nam)" },
  { value: "vieneu:Trúc Ly", label: "VieNeu CPU: Trúc Ly (Nữ Bắc)" },
  { value: "vieneu:Minh Quân", label: "VieNeu CPU: Minh Quân (Nam Bắc)" },
  { value: "vieneu:Ái Hân", label: "VieNeu CPU: Ái Hân (Nữ Nam)" },
  { value: "vieneu:Adam", label: "VieNeu CPU: Adam (Nam Nam)" },
  { value: "en-US-JennyNeural", label: "Edge TTS: Jenny (EN)" },
  { value: "en-US-GuyNeural", label: "Edge TTS: Guy (EN)" },
];

export default function PodcastStudioPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [projects, setProjects] = useState<PodcastProject[]>([]);
  const [channelVoices, setChannelVoices] = useState<ChannelVoiceOption[]>([]);

  const [title, setTitle] = useState("");
  const [hostA, setHostA] = useState("Lan Anh");
  const [hostB, setHostB] = useState("Minh Quân");
  const [hostAVoice, setHostAVoice] = useState("vi-VN-HoaiMyNeural");
  const [hostBVoice, setHostBVoice] = useState("vi-VN-NamMinhNeural");
  const [aspectRatio, setAspectRatio] = useState("16:9");
  const [waveformStyle, setWaveformStyle] = useState("spectrum");
  const [accentColor, setAccentColor] = useState("#38bdf8");
  const [scriptText, setScriptText] = useState("");
  const [renderingId, setRenderingId] = useState<number | null>(null);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [res, cvRes] = await Promise.all([
        apiFetch<{ projects: PodcastProject[] }>(
          `/api/v1/podcasts/projects?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ channel_voices: ChannelVoiceOption[] }>(
          `/api/v1/channel-voices?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      setProjects(res.projects || []);
      setChannelVoices(cvRes.channel_voices || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Studio Podcast");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const { job: activeJob, isRunning: jobRunning } = useJobProgress(activeJobId, {
    onCompleted: () => {
      setMsg(
        `Đã xuất xong video Sóng nhạc Podcast #${renderingId ?? ""} (Avatar sáng theo lượt nói + -14 LUFS + QC).`
      );
      setRenderingId(null);
      void load();
    },
    onFailed: (j) => {
      setErr(j.error || "Lỗi dựng Podcast trong hàng đợi");
      setRenderingId(null);
      void load();
    },
  });

  const voiceChoices = [
    ...channelVoices.map((cv) => ({
      value: cv.voice_token,
      label: `Giọng Kênh: ${cv.name} (${cv.speaker_name})`,
    })),
    ...BASE_PODCAST_VOICES,
  ];

  const createPodcast = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ project: PodcastProject }>("/api/v1/podcasts/projects", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          title: title || "Podcast Audio Spectrum",
          host_a_name: hostA,
          host_b_name: hostB,
          host_a_voice: hostAVoice,
          host_b_voice: hostBVoice,
          aspect_ratio: aspectRatio,
          waveform_style: waveformStyle,
          accent_color: accentColor,
          script_text: scriptText,
        }),
      });
      setTitle("");
      setScriptText("");
      setMsg(`Đã tạo tập Podcast #${res.project.id} (${res.project.aspect_ratio}).`);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo Podcast");
    }
  };

  const renderPodcast = async (pid: number) => {
    setRenderingId(pid);
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ job_id: number }>(`/api/v1/podcasts/projects/${pid}/render`, {
        method: "POST",
        body: JSON.stringify({ sync: false }),
      });
      setActiveJobId(res.job_id);
      setMsg(`Đã xếp hàng dựng Podcast #${pid} (Job #${res.job_id}) — đang theo dõi trực tiếp qua SSE.`);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi dựng Podcast");
      setRenderingId(null);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Mic className="w-6 h-6 text-sky-400" /> Studio Sóng nhạc Podcast (16:9 / 9:16 / 1:1)
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Hội thoại 2 Host bằng giọng thật Edge TTS / VieNeu / Giọng Kênh MC, ảnh đại diện sáng lên theo đúng lượt nói và phổ âm thanh chuẩn -14 LUFS.
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
        label={renderingId ? `Podcast #${renderingId}` : "Podcast Studio"}
        onDismiss={() => setActiveJobId(null)}
      />

      <form
        onSubmit={createPodcast}
        className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs"
      >
        <div className="grid md:grid-cols-3 gap-3">
          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Tiêu đề tập Podcast"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <input
            value={hostA}
            onChange={(e) => setHostA(e.target.value)}
            placeholder="Tên Host A"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <input
            value={hostB}
            onChange={(e) => setHostB(e.target.value)}
            placeholder="Tên Host B"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <select
            value={hostAVoice}
            onChange={(e) => setHostAVoice(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            {voiceChoices.map((v) => (
              <option key={`a-${v.value}`} value={v.value}>
                Giọng Host A: {v.label}
              </option>
            ))}
          </select>
          <select
            value={hostBVoice}
            onChange={(e) => setHostBVoice(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            {voiceChoices.map((v) => (
              <option key={`b-${v.value}`} value={v.value}>
                Giọng Host B: {v.label}
              </option>
            ))}
          </select>
          <select
            value={aspectRatio}
            onChange={(e) => setAspectRatio(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="16:9">16:9 YouTube Ngang (Mặc định Podcast)</option>
            <option value="9:16">9:16 Shorts / TikTok</option>
            <option value="1:1">1:1 Vuông</option>
          </select>
          <select
            value={waveformStyle}
            onChange={(e) => setWaveformStyle(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2 md:col-span-2"
          >
            <option value="spectrum">Phổ tần số AI Spectrum (showfreqs)</option>
            <option value="bars">Cột tần số Logarit (bars)</option>
            <option value="cline">Sóng trung tâm mượt (cline)</option>
            <option value="p2p">Sóng biên độ Đỉnh-Đỉnh (p2p)</option>
            <option value="line">Đường sóng mảnh (line)</option>
          </select>
          <input
            value={accentColor}
            onChange={(e) => setAccentColor(e.target.value)}
            placeholder="#38bdf8"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2 font-mono"
          />
        </div>
        <textarea
          required
          rows={4}
          value={scriptText}
          onChange={(e) => setScriptText(e.target.value)}
          placeholder={"Mỗi dòng là một lượt thoại luân phiên giữa Host A và Host B..."}
          className="w-full bg-[#182235] border border-slate-700 rounded-lg p-3"
        />
        <button
          type="submit"
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
        >
          <Plus className="w-4 h-4" /> Tạo Tập Podcast
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
                  {p.aspect_ratio} • Sóng: {p.waveform_style} • {p.host_a_name} &amp; {p.host_b_name} •{" "}
                  <span className="text-sky-300">{p.status}</span>
                </div>
              </div>
              <button
                type="button"
                disabled={jobRunning && renderingId === p.id}
                onClick={() => void renderPodcast(p.id)}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold cursor-pointer disabled:opacity-50"
              >
                <Play className="w-3.5 h-3.5" />{" "}
                {jobRunning && renderingId === p.id ? "Đang dựng..." : "Render"}
              </button>
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
