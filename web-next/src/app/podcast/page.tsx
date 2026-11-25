"use client";

import React, { useState } from "react";
import { Mic, Play, Plus } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, ChannelVoiceOption, useWorkspace } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import { JobProgressBanner, useJobProgress } from "@/components/JobProgressBanner";
import { SimulationBadge } from "@/components/SimulationBadge";
import { PageHeader } from "@/components/vc/PageHeader";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  TextareaBox,
  TextInput,
} from "@/components/ui/form-controls";

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
  const [title, setTitle] = useState("");
  const [hostA, setHostA] = useState("Lan Anh");
  const [hostB, setHostB] = useState("Minh Quân");
  const [hostAVoice, setHostAVoice] = useState("vi-VN-HoaiMyNeural");
  const [hostBVoice, setHostBVoice] = useState("vi-VN-NamMinhNeural");
  const [aspectRatio, setAspectRatio] = useState("16:9");
  const [waveformStyle, setWaveformStyle] = useState("spectrum");
  const [accentColor, setAccentColor] = useState("#a78bfa");
  const [scriptText, setScriptText] = useState("");
  const [renderingId, setRenderingId] = useState<number | null>(null);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");

  const { data, error: err, setError: setErr, reload: load } = useApiQuery<{
    projects: PodcastProject[];
    channelVoices: ChannelVoiceOption[];
  }>(
    async (signal) => {
      const [res, cvRes] = await Promise.all([
        apiFetch<{ projects: PodcastProject[] }>(
          `/api/v1/podcasts/projects?workspace_id=${activeWorkspaceId}`,
          { signal }
        ),
        apiFetch<{ channel_voices: ChannelVoiceOption[] }>(
          `/api/v1/channel-voices?workspace_id=${activeWorkspaceId}`,
          { signal }
        ),
      ]);
      return {
        projects: res.projects || [],
        channelVoices: cvRes.channel_voices || [],
      };
    },
    [activeWorkspaceId],
    { fallbackError: "Lỗi tải Studio Podcast" }
  );

  const projects = data?.projects || [];
  const channelVoices = data?.channelVoices || [];

  const { job: activeJob, isRunning: jobRunning } = useJobProgress(activeJobId, {
    onCompleted: () => {
      const done = `Đã xuất xong video Podcast #${renderingId ?? ""} (Avatar sáng theo lượt nói + chuẩn -14 LUFS).`;
      setMsg(done);
      toast.success(done);
      setRenderingId(null);
      void load();
    },
    onFailed: (j) => {
      setErr(j.error || "Lỗi xuất Podcast");
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
      const res = await apiFetch<{ project: PodcastProject }>(
        "/api/v1/podcasts/projects",
        {
          method: "POST",
          body: JSON.stringify({
            workspace_id: activeWorkspaceId,
            title: title || "Podcast Đối Thoại",
            host_a_name: hostA,
            host_b_name: hostB,
            host_a_voice: hostAVoice,
            host_b_voice: hostBVoice,
            aspect_ratio: aspectRatio,
            waveform_style: waveformStyle,
            accent_color: accentColor,
            script_text: scriptText,
          }),
        }
      );
      setTitle("");
      setScriptText("");
      const m = `Đã tạo tập Podcast #${res.project.id} (${res.project.aspect_ratio}).`;
      setMsg(m);
      toast.success(m);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo tập Podcast");
    }
  };

  const renderPodcast = async (pid: number) => {
    setRenderingId(pid);
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ job_id: number }>(
        `/api/v1/podcasts/projects/${pid}/render`,
        {
          method: "POST",
          body: JSON.stringify({ sync: false }),
        }
      );
      setActiveJobId(res.job_id);
      const m = `Đã đưa tập Podcast #${pid} vào hàng đợi xuất video (Tác vụ #${res.job_id}).`;
      setMsg(m);
      toast.info(m);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi xuất Podcast");
      setRenderingId(null);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <PageHeader
        icon={<Mic className="w-5 h-5" />}
        title="Podcast Sóng Nhạc Đối Thoại 2 MC"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {projects.length} tập Podcast
          </Badge>
        }
        description="Đối thoại tự nhiên giữa 2 người dẫn (Edge TTS / VieNeu CPU / Giọng Kênh MC), vòng sáng đại diện bật theo đúng người đang nói và sóng nhạc chuẩn -14 LUFS."
      />

      {msg && (
        <div
          role="status"
          className="rounded-[11px] border border-[var(--st-emerald-bd)] bg-[var(--st-emerald-bg)] px-4 py-2.5 text-[13px] text-[var(--st-emerald-tx)]"
        >
          {msg}
        </div>
      )}
      {err && (
        <div
          role="alert"
          className="rounded-[11px] border border-[var(--st-rose-bd)] bg-[var(--st-rose-bg)] px-4 py-2.5 text-[13px] text-[var(--st-rose-tx)]"
        >
          {err}
        </div>
      )}

      <JobProgressBanner
        job={activeJob}
        jobId={activeJobId}
        label={renderingId ? `Podcast #${renderingId}` : "Studio Podcast"}
        onDismiss={() => setActiveJobId(null)}
      />

      <Card tinted>
        <form onSubmit={createPodcast} className="space-y-4">
          <SectionHeading>
            <Plus className="w-4 h-4 text-[var(--c-icon)]" /> Tạo Tập Podcast Mới
          </SectionHeading>

          <div className="grid md:grid-cols-3 gap-3.5">
            <div>
              <FieldLabel htmlFor="pd-title">Tiêu đề tập Podcast *</FieldLabel>
              <TextInput
                id="pd-title"
                required
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="VD: Chuyện Nghề Chế Tác Bạc Thủ Công"
              />
            </div>
            <div>
              <FieldLabel htmlFor="pd-ha">Tên Người dẫn A</FieldLabel>
              <TextInput
                id="pd-ha"
                value={hostA}
                onChange={(e) => setHostA(e.target.value)}
              />
            </div>
            <div>
              <FieldLabel htmlFor="pd-hb">Tên Người dẫn B</FieldLabel>
              <TextInput
                id="pd-hb"
                value={hostB}
                onChange={(e) => setHostB(e.target.value)}
              />
            </div>
            <div>
              <FieldLabel htmlFor="pd-va">Giọng Người dẫn A</FieldLabel>
              <SelectBox
                id="pd-va"
                value={hostAVoice}
                onChange={(e) => setHostAVoice(e.target.value)}
              >
                {voiceChoices.map((v) => (
                  <option key={`a-${v.value}`} value={v.value}>
                    {v.label}
                  </option>
                ))}
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="pd-vb">Giọng Người dẫn B</FieldLabel>
              <SelectBox
                id="pd-vb"
                value={hostBVoice}
                onChange={(e) => setHostBVoice(e.target.value)}
              >
                {voiceChoices.map((v) => (
                  <option key={`b-${v.value}`} value={v.value}>
                    {v.label}
                  </option>
                ))}
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="pd-ratio">Tỷ lệ khung hình</FieldLabel>
              <SelectBox
                id="pd-ratio"
                value={aspectRatio}
                onChange={(e) => setAspectRatio(e.target.value)}
              >
                <option value="16:9">16:9 Ngang (YouTube Podcast)</option>
                <option value="9:16">9:16 Dọc (Shorts / TikTok)</option>
                <option value="1:1">1:1 Vuông</option>
              </SelectBox>
            </div>
            <div className="md:col-span-2">
              <FieldLabel htmlFor="pd-wave">Kiểu hiệu ứng sóng âm</FieldLabel>
              <SelectBox
                id="pd-wave"
                value={waveformStyle}
                onChange={(e) => setWaveformStyle(e.target.value)}
              >
                <option value="spectrum">Phổ tần số chuyển động (Spectrum)</option>
                <option value="bars">Cột tần số nhịp điệu (Bars)</option>
                <option value="cline">Sóng trung tâm mượt (Cline)</option>
                <option value="p2p">Sóng biên độ Đỉnh–Đỉnh (P2P)</option>
                <option value="line">Đường sóng thanh mảnh (Line)</option>
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="pd-color">Màu sóng âm trên video</FieldLabel>
              <TextInput
                id="pd-color"
                value={accentColor}
                onChange={(e) => setAccentColor(e.target.value)}
                className="font-mono"
              />
            </div>
          </div>

          <div>
            <FieldLabel htmlFor="pd-script">
              Kịch bản đối thoại * (mỗi dòng là 1 lượt nói luân phiên A và B)
            </FieldLabel>
            <TextareaBox
              id="pd-script"
              required
              rows={4}
              value={scriptText}
              onChange={(e) => setScriptText(e.target.value)}
              placeholder="Chào mừng các bạn quay lại chuyên mục hôm nay..."
            />
          </div>

          <Button type="submit">
            <Plus className="w-4 h-4" /> Tạo Tập Podcast
          </Button>
        </form>
      </Card>

      {projects.length === 0 ? (
        <EmptyState
          icon={<Mic className="w-5 h-5" />}
          title="Chưa có tập Podcast nào"
          description="Tạo tập Podcast đầu tiên ở biểu mẫu trên để xuất video sóng nhạc."
        />
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {projects.map((p) => (
            <Card key={p.id} className="space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-[15px] font-bold text-[var(--text-primary)]">
                    #{p.id} — {p.title}
                  </div>
                  <div className="mt-0.5 text-[12px] text-[var(--text-muted)]">
                    {p.aspect_ratio} • Sóng: {p.waveform_style} • {p.host_a_name} &amp;{" "}
                    {p.host_b_name} •{" "}
                    <strong className="text-[var(--c-tx)]">{p.status}</strong>
                  </div>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="emerald"
                  disabled={jobRunning && renderingId === p.id}
                  onClick={() => void renderPodcast(p.id)}
                >
                  <Play className="w-3.5 h-3.5" />{" "}
                  {jobRunning && renderingId === p.id ? "Đang dựng..." : "Xuất MP4"}
                </Button>
              </div>
              {p.video_url && (
                <video
                  controls
                  preload="metadata"
                  src={p.video_url}
                  className="w-full max-h-56 rounded-[9px] bg-black"
                />
              )}
              <SimulationBadge flags={p.simulation_flags} />
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
