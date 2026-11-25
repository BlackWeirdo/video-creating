"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ExternalLink, Film, Play, Plus, Scissors, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import { JobProgressBanner, useJobProgress } from "@/components/JobProgressBanner";
import { PageHeader } from "@/components/vc/PageHeader";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextInput } from "@/components/ui/form-controls";
import { TabPanel, TabsBar, TabsRoot, TabTrigger } from "@/components/ui/overlays";

interface MediaClip {
  id: number;
  url: string;
  output_path?: string;
  media_path?: string;
  duration_s?: number;
  description?: string;
}

interface TimelineClip {
  source_path: string;
  start_s: number;
  duration_s: number;
}

interface EditorProject {
  id: number;
  title: string;
  status: string;
  output_video_id: number | null;
  tracks: {
    video_clips: TimelineClip[];
    subtitles: Array<{ start_s: number; end_s: number; text: string }>;
  };
}

export default function EditorPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [selectedJob, setSelectedJob] = useState<string>("");
  const [clips, setClips] = useState<TimelineClip[]>([]);
  const [subText, setSubText] = useState("Tiêu đề bản dựng đa kênh");
  const [projTitle, setProjTitle] = useState("Bản dựng đa lớp mới");
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");

  const { data, error: err, setError: setErr, reload: load } = useApiQuery<{
    videos: MediaClip[];
    shots: MediaClip[];
    projects: EditorProject[];
  }>(
    async (signal) => {
      const [mRes, pRes] = await Promise.all([
        apiFetch<{ videos: MediaClip[]; shots: MediaClip[] }>(
          `/api/v1/editor/media?workspace_id=${activeWorkspaceId}`,
          { signal }
        ),
        apiFetch<{ projects: EditorProject[] }>(
          `/api/v1/editor/projects?workspace_id=${activeWorkspaceId}`,
          { signal }
        ),
      ]);
      return {
        videos: mRes.videos || [],
        shots: mRes.shots || [],
        projects: pRes.projects || [],
      };
    },
    [activeWorkspaceId],
    {
      fallbackError: "Lỗi tải Trình dựng",
      onSuccess: (bundle) => {
        setSelectedJob((prev) =>
          prev || (bundle.videos.length > 0 ? String(bundle.videos[0].id) : "")
        );
      },
    }
  );

  const videos = data?.videos || [];
  const shots = data?.shots || [];
  const projects = data?.projects || [];

  const { job: activeJob, isRunning: jobRunning } = useJobProgress(activeJobId, {
    onCompleted: () => {
      const done = "Đã xuất xong video ghép đa lớp!";
      setMsg(done);
      toast.success(done);
      void load();
    },
    onFailed: (j) => {
      setErr(j.error || "Lỗi xuất bản dựng");
      void load();
    },
  });

  const renderTimeline = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const cr = await apiFetch<{ project: EditorProject }>(
        "/api/v1/editor/projects",
        {
          method: "POST",
          body: JSON.stringify({
            workspace_id: activeWorkspaceId,
            title: projTitle,
            tracks: {
              video_clips: clips,
              audio_clips: [],
              subtitles: subText.trim()
                ? [
                    {
                      start_s: 0.1,
                      end_s: Math.max(
                        2.0,
                        clips.reduce((s, c) => s + c.duration_s, 0) - 0.1
                      ),
                      text: subText,
                    },
                  ]
                : [],
            },
          }),
        }
      );
      const rn = await apiFetch<{ job_id: number }>(
        `/api/v1/editor/projects/${cr.project.id}/render`,
        {
          method: "POST",
          body: JSON.stringify({ style_preset: "tiktok_karaoke", sync: false }),
        }
      );
      setActiveJobId(rn.job_id);
      const m = `Đã đưa bản dựng #${cr.project.id} vào hàng đợi xử lý (Tác vụ #${rn.job_id}).`;
      setMsg(m);
      toast.info(m);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi xuất bản dựng");
    }
  };

  const freecutUrl = selectedJob
    ? `/freecut/?job=${encodeURIComponent(selectedJob)}`
    : "/freecut/";

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      <PageHeader
        icon={<Scissors className="w-5 h-5" />}
        title="Trình Dựng Video Trực Quan (FreeCut)"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {projects.length} bản dựng
          </Badge>
        }
        description="Cắt ghép từng khung hình bằng trình dựng FreeCut nhúng sẵn hoặc nối nhanh nhiều đoạn Shot trên máy chủ."
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
        label="Trình dựng đa lớp"
        onDismiss={() => setActiveJobId(null)}
      />

      <TabsRoot defaultValue="freecut" className="space-y-4">
        <TabsBar aria-label="Chế độ trình dựng">
          <TabTrigger value="freecut">
            <Scissors className="w-4 h-4" /> Trình dựng FreeCut (Nhúng)
          </TabTrigger>
          <TabTrigger value="timeline">
            <Film className="w-4 h-4" /> Ghép Nhanh Đa Đoạn ({projects.length})
          </TabTrigger>
        </TabsBar>

        <TabPanel value="freecut" className="space-y-3">
          <Card className="flex flex-wrap items-center justify-between gap-3 p-3.5">
            <div className="flex flex-wrap items-center gap-2.5">
              <FieldLabel htmlFor="ed-pick-vid" className="mb-0">
                Mở Video trong FreeCut:
              </FieldLabel>
              <SelectBox
                id="ed-pick-vid"
                value={selectedJob}
                onChange={(e) => setSelectedJob(e.target.value)}
                className="w-64 min-h-[34px] py-1"
              >
                <option value="">-- Bàn dựng trống --</option>
                {videos.map((v) => (
                  <option key={v.id} value={String(v.id)}>
                    Video #{v.id} ({v.duration_s ? `${v.duration_s}s` : "—"})
                  </option>
                ))}
              </SelectBox>
            </div>
            <Button asChild size="sm" variant="secondary">
              <a href={freecutUrl} target="_blank" rel="noreferrer">
                <ExternalLink className="w-3.5 h-3.5" /> Mở cửa sổ lớn
              </a>
            </Button>
          </Card>

          <div className="h-[640px] overflow-hidden rounded-[14px] border border-[var(--border-strong)] bg-black shadow-[var(--shadow-md)]">
            <iframe
              src={freecutUrl}
              title="FreeCut Studio"
              className="h-full w-full border-0"
            />
          </div>
        </TabPanel>

        <TabPanel value="timeline">
          <div className="grid lg:grid-cols-2 gap-4">
            <Card className="space-y-3">
              <SectionHeading>
                <Film className="w-4 h-4 text-[var(--c-icon)]" /> Kho Cảnh Quay &amp; Video Workspace
              </SectionHeading>

              {shots.length === 0 && videos.length === 0 ? (
                <EmptyState title="Chưa có cảnh quay hoặc video nào để ghép" />
              ) : (
                <div className="space-y-2 max-h-80 overflow-y-auto">
                  {shots.map((s) => (
                    <div
                      key={`s-${s.id}`}
                      className="flex items-center justify-between gap-2 rounded-[9px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px]"
                    >
                      <span className="truncate">
                        Shot #{s.id} — {s.description || "Đoạn quay"}
                      </span>
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          setClips((prev) => [
                            ...prev,
                            {
                              source_path: s.media_path || "",
                              start_s: 0,
                              duration_s: 2.5,
                            },
                          ])
                        }
                      >
                        <Plus className="w-3.5 h-3.5" /> Thêm
                      </Button>
                    </div>
                  ))}
                  {videos.map((v) => (
                    <div
                      key={`v-${v.id}`}
                      className="flex items-center justify-between gap-2 rounded-[9px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px]"
                    >
                      <span className="tabular-nums">
                        Video #{v.id} ({v.duration_s ?? "?"}s)
                      </span>
                      <Button
                        type="button"
                        size="sm"
                        variant="emerald"
                        onClick={() =>
                          setClips((prev) => [
                            ...prev,
                            {
                              source_path: v.output_path || "",
                              start_s: 0,
                              duration_s: v.duration_s || 2.5,
                            },
                          ])
                        }
                      >
                        <Plus className="w-3.5 h-3.5" /> Thêm
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <Card tinted>
              <form onSubmit={renderTimeline} className="space-y-3.5">
                <SectionHeading className="tabular-nums">
                  Chuỗi Nối Đoạn ({clips.length} đoạn)
                </SectionHeading>

                <div>
                  <FieldLabel htmlFor="ed-title">Tên bản dựng</FieldLabel>
                  <TextInput
                    id="ed-title"
                    value={projTitle}
                    onChange={(e) => setProjTitle(e.target.value)}
                  />
                </div>

                {clips.length > 0 && (
                  <div className="space-y-1.5 max-h-44 overflow-y-auto">
                    {clips.map((c, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between gap-2 rounded-[9px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3 py-1.5 text-[12.5px]"
                      >
                        <span className="truncate">
                          {c.source_path} ({c.duration_s}s)
                        </span>
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          aria-label="Gỡ đoạn"
                          onClick={() =>
                            setClips((prev) => prev.filter((_, i) => i !== idx))
                          }
                        >
                          <Trash2 className="w-4 h-4 text-rose-400" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}

                <div>
                  <FieldLabel htmlFor="ed-sub">Dòng phụ đề chạy xuyên suốt</FieldLabel>
                  <TextInput
                    id="ed-sub"
                    value={subText}
                    onChange={(e) => setSubText(e.target.value)}
                  />
                </div>

                <Button
                  type="submit"
                  disabled={clips.length === 0 || jobRunning}
                >
                  <Play className="w-4 h-4" />{" "}
                  {jobRunning ? "Đang xuất..." : "Xuất Video Đa Đoạn"}
                </Button>

                {projects.slice(0, 3).map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center justify-between border-t border-[var(--border-subtle)] pt-2 text-[12.5px] text-[var(--text-muted)]"
                  >
                    <span>
                      #{p.id} {p.title} ({p.status})
                    </span>
                    {p.output_video_id && (
                      <Link
                        href={`/videos/${p.output_video_id}`}
                        className="font-semibold text-[var(--c-tx)] hover:underline"
                      >
                        Video #{p.output_video_id} →
                      </Link>
                    )}
                  </div>
                ))}
              </form>
            </Card>
          </div>
        </TabPanel>
      </TabsRoot>
    </div>
  );
}
