"use client";

import React, { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Clapperboard,
  Download,
  Play,
  RefreshCw,
  Save,
  Volume2,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import {
  VideoPreviewAndQcCard,
  type VideoQcInfo,
} from "@/app/videos/[id]/_components/VideoPreviewAndQcCard";
import { JobProgressBanner, useJobProgress } from "@/components/JobProgressBanner";
import { PageHeader } from "@/components/vc/PageHeader";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  TextareaBox,
  TextInput,
} from "@/components/ui/form-controls";

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
    shots?: Array<{
      shot_id: number;
      start_s: number;
      duration_s: number;
      text: string;
    }>;
  };
  qc: VideoQcInfo;
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
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");

  const { error: err, setError: setErr, reload: load } = useApiQuery<{
    video: VideoDetail;
    styles: StylePreset[];
  }>(
    async (signal) => {
      const res = await apiFetch<{ video: VideoDetail }>(
        `/api/v1/videos/${videoId}`,
        { signal }
      );
      const v = res.video;
      const st = await apiFetch<{ styles: StylePreset[] }>(
        `/api/v1/styles?workspace_id=${v.workspace_id}`,
        { signal }
      );
      return { video: v, styles: st.styles || [] };
    },
    [videoId],
    {
      fallbackError: "Không tải được chi tiết video",
      onSuccess: ({ video: v, styles: stList }) => {
        setVideo(v);
        setStyles(stList);
        setTitle(v.plan?.title || "");
        setShots(v.plan?.shots || []);
        setStyleId(v.style_preset || "tiktok_karaoke");
        setRatio(v.aspect_ratio || "9:16");
        setVoiceLang(v.voice_lang || "vi");
      },
    }
  );

  const { job: activeJob } = useJobProgress(activeJobId, {
    onCompleted: () => {
      const done = "Đã hoàn tất xuất video thành phẩm!";
      setMsg(done);
      toast.success(done);
      void load();
    },
    onFailed: (j) => {
      setErr(j.error || "Tác vụ dựng video gặp lỗi");
      void load();
    },
  });

  const handleSavePlan = async () => {
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ video: VideoDetail }>(
        `/api/v1/videos/${videoId}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            title,
            shots,
            style_preset: styleId,
            aspect_ratio: ratio,
            voice_lang: voiceLang,
          }),
        }
      );
      setVideo(res.video);
      setMsg("Đã lưu kịch bản và cập nhật đồng hồ âm tiết.");
      toast.success("Đã lưu kịch bản.");
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
      setErr(e instanceof Error ? e.message : "Không thể đọc thử giọng");
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
      if (res.job_id) setActiveJobId(res.job_id);
      const m = `Đã đưa tác vụ dựng video vào hàng đợi xử lý (#${res.job_id}).`;
      setMsg(m);
      toast.info(m);
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
        {
          method: "POST",
          body: JSON.stringify({ style_preset: styleId, sync: false }),
        }
      );
      if (res.job_id) setActiveJobId(res.job_id);
      const m = `Đã đưa vào hàng đợi đổi phong cách sang "${styleId}" (#${res.job_id}).`;
      setMsg(m);
      toast.info(m);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Không thể đổi phong cách");
    }
  };

  if (!video) {
    return (
      <div className="max-w-5xl mx-auto py-8 text-[14px] text-[var(--text-muted)]">
        {err || "Đang tải chi tiết video..."}
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        icon={<Clapperboard className="w-5 h-5" />}
        title={`Video #${video.id} — ${video.plan?.title || "Biên tập kịch bản"}`}
        badges={
          <>
            <Badge tone="cluster">{video.status}</Badge>
            <Badge tone="neutral" className="tabular-nums">
              {video.duration_s
                ? `${video.duration_s.toFixed(1)}s`
                : "Chưa xuất MP4"}
            </Badge>
          </>
        }
        actions={
          <>
            <Button asChild size="sm" variant="ghost">
              <Link href="/videos">
                <ArrowLeft className="w-4 h-4" /> Danh sách
              </Link>
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => void handleSavePlan()}
            >
              <Save className="w-3.5 h-3.5" /> Lưu Kịch bản
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => void handleRestyle()}
            >
              <RefreshCw className="w-3.5 h-3.5" /> Đổi Phong cách
            </Button>
            {video.output_url && (
              <Button asChild size="sm" variant="emerald">
                <a href={`/api/v1/videos/${video.id}/publish-pack`}>
                  <Download className="w-3.5 h-3.5" /> Gói 5 MXH (.zip)
                </a>
              </Button>
            )}
            <Button type="button" size="sm" onClick={() => void handleRender()}>
              <Play className="w-3.5 h-3.5" /> Dựng Video
            </Button>
          </>
        }
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
        label={`Video #${video.id}`}
        onDismiss={() => setActiveJobId(null)}
      />

      <div className="grid lg:grid-cols-5 gap-5">
        <Card tinted className="lg:col-span-3 space-y-4">
          <div className="grid sm:grid-cols-3 gap-3">
            <div>
              <FieldLabel htmlFor="vd-title">Tiêu đề</FieldLabel>
              <TextInput
                id="vd-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
            <div>
              <FieldLabel htmlFor="vd-style">Phong cách phụ đề</FieldLabel>
              <SelectBox
                id="vd-style"
                value={styleId}
                onChange={(e) => setStyleId(e.target.value)}
              >
                {styles.map((st) => (
                  <option key={st.id} value={st.id}>
                    {st.name}
                  </option>
                ))}
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="vd-ratio">Khung hình &amp; Giọng đọc</FieldLabel>
              <div className="flex gap-2">
                <SelectBox
                  id="vd-ratio"
                  value={ratio}
                  onChange={(e) =>
                    setRatio(e.target.value as "9:16" | "16:9" | "1:1")
                  }
                >
                  <option value="9:16">9:16</option>
                  <option value="16:9">16:9</option>
                  <option value="1:1">1:1</option>
                </SelectBox>
                <SelectBox
                  aria-label="Ngôn ngữ giọng đọc"
                  value={voiceLang}
                  onChange={(e) =>
                    setVoiceLang(e.target.value as "none" | "vi" | "en")
                  }
                >
                  <option value="vi">VI</option>
                  <option value="en">EN</option>
                  <option value="none">Tắt</option>
                </SelectBox>
              </div>
            </div>
          </div>

          <div className="space-y-3">
            <SectionHeading>
              Lời thoại từng cảnh &amp; Hạn mức âm tiết
            </SectionHeading>
            {shots.map((shot, idx) => {
              const budget = video.syllable_budget?.[idx];
              return (
                <div
                  key={idx}
                  className="rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5 space-y-2"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2 text-[12.5px]">
                    <strong className="text-[var(--text-primary)] tabular-nums">
                      Cảnh #{idx + 1} (Shot #{shot.shot_id} • {shot.duration_s}s)
                    </strong>
                    <div className="flex items-center gap-2">
                      {budget && (
                        <Badge
                          tone={budget.over_budget ? "amber" : "emerald"}
                          className="tabular-nums"
                        >
                          {budget.syllables}/{budget.max_syllables} âm tiết
                        </Badge>
                      )}
                      {shot.text && (
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          onClick={() => void handlePreviewVoice(shot.text)}
                        >
                          <Volume2 className="w-3.5 h-3.5 text-[var(--c-icon)]" /> Nghe thử
                        </Button>
                      )}
                    </div>
                  </div>
                  <TextareaBox
                    aria-label={`Lời thoại cảnh #${idx + 1}`}
                    rows={2}
                    value={shot.text}
                    onChange={(e) => {
                      const val = e.target.value;
                      setShots((prev) =>
                        prev.map((s, i) => (i === idx ? { ...s, text: val } : s))
                      );
                    }}
                  />
                </div>
              );
            })}

            {ttsAudioUrl && (
              <div className="pt-1">
                <div className="text-[12px] text-[var(--text-muted)] mb-1">
                  Âm thanh nghe thử:
                </div>
                <audio controls src={ttsAudioUrl} className="w-full h-8" />
              </div>
            )}
          </div>
        </Card>

        <VideoPreviewAndQcCard outputUrl={video.output_url} qc={video.qc} />
      </div>
    </div>
  );
}
