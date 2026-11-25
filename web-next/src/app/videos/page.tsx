"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Clapperboard, Plus } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { PageHeader } from "@/components/vc/PageHeader";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextInput } from "@/components/ui/form-controls";

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
        apiFetch<{ videos: VideoSummary[] }>(
          `/api/v1/videos?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ shots: ShotOption[] }>(
          `/api/v1/shots?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ styles: StyleOption[] }>(
          `/api/v1/styles?workspace_id=${activeWorkspaceId}`
        ),
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
      const durS = shotObj
        ? Math.max(1.5, Math.min(5.0, shotObj.end_s - shotObj.start_s))
        : 3.0;
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
              ? [
                  {
                    shot_id: selectedShotId,
                    start_s: startS,
                    duration_s: durS,
                    text: lineText,
                  },
                ]
              : [],
          },
        }),
      });
      setTitle("");
      setLineText("");
      toast.success("Đã khởi tạo kịch bản video mới.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo kịch bản video");
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        icon={<Clapperboard className="w-5 h-5" />}
        title="Kịch bản & Sản Xuất Video"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {videos.length} kịch bản
          </Badge>
        }
        description="Lập kịch bản gắn cảnh quay thật, biên tập lời bình khớp hạn mức âm tiết, xuất video chuẩn -14 LUFS và đổi phong cách phụ đề nhanh."
      />

      {err && (
        <div
          role="alert"
          className="rounded-[11px] border border-[var(--st-rose-bd)] bg-[var(--st-rose-bg)] px-4 py-2.5 text-[13px] text-[var(--st-rose-tx)]"
        >
          {err}
        </div>
      )}

      <Card tinted>
        <form onSubmit={handleCreate} className="space-y-4">
          <SectionHeading>
            <Plus className="w-4 h-4 text-[var(--c-icon)]" /> Khởi Tạo Kịch Bản Video Mới
          </SectionHeading>

          <div className="grid md:grid-cols-4 gap-3.5">
            <div className="md:col-span-2">
              <FieldLabel htmlFor="vid-title">Tiêu đề video *</FieldLabel>
              <TextInput
                id="vid-title"
                required
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="VD: 3 lý do nên chọn bạc S925 phủ bạch kim..."
              />
            </div>
            <div>
              <FieldLabel htmlFor="vid-style">Phong cách phụ đề</FieldLabel>
              <SelectBox
                id="vid-style"
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
              <FieldLabel htmlFor="vid-ratio">Tỷ lệ khung hình</FieldLabel>
              <SelectBox
                id="vid-ratio"
                value={ratio}
                onChange={(e) =>
                  setRatio(e.target.value as "9:16" | "16:9" | "1:1")
                }
              >
                <option value="9:16">9:16 Dọc (Shorts / Reels)</option>
                <option value="16:9">16:9 Ngang (YouTube)</option>
                <option value="1:1">1:1 Vuông</option>
              </SelectBox>
            </div>
          </div>

          <div className="grid md:grid-cols-3 gap-3.5">
            <div>
              <FieldLabel htmlFor="vid-shot">Cảnh mở đầu (Shot)</FieldLabel>
              <SelectBox
                id="vid-shot"
                value={selectedShotId}
                onChange={(e) => setSelectedShotId(Number(e.target.value))}
              >
                <option value={0}>-- Chọn cảnh quay đầu tiên --</option>
                {shots.map((s) => (
                  <option key={s.id} value={s.id}>
                    Shot #{s.id}: {s.description || `${s.start_s}s–${s.end_s}s`}
                  </option>
                ))}
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="vid-voice">Ngôn ngữ giọng đọc</FieldLabel>
              <SelectBox
                id="vid-voice"
                value={voiceLang}
                onChange={(e) =>
                  setVoiceLang(e.target.value as "none" | "vi" | "en")
                }
              >
                <option value="vi">Giọng đọc Tiếng Việt</option>
                <option value="en">Giọng đọc Tiếng Anh</option>
                <option value="none">Không lồng tiếng (chỉ nhạc nền)</option>
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="vid-line">Lời bình / phụ đề mở đầu</FieldLabel>
              <TextInput
                id="vid-line"
                value={lineText}
                onChange={(e) => setLineText(e.target.value)}
                placeholder="Nhập câu dẫn mở đầu..."
              />
            </div>
          </div>

          <Button type="submit">Tạo Kịch Bản Video</Button>
        </form>
      </Card>

      {videos.length === 0 ? (
        <EmptyState
          icon={<Clapperboard className="w-5 h-5" />}
          title="Chưa có kịch bản video nào"
          description="Điền biểu mẫu phía trên để tạo kịch bản đầu tiên cho Workspace này."
        />
      ) : (
        <div className="grid md:grid-cols-3 gap-4">
          {videos.map((v) => (
            <Link key={v.id} href={`/videos/${v.id}`} className="block group">
              <Card className="h-full space-y-2.5 group-hover:border-[var(--c-bd)] transition-all">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[14px] font-bold text-[var(--text-primary)] line-clamp-1">
                    #{v.id} — {v.plan?.title || "Chưa đặt tiêu đề"}
                  </span>
                  <Badge
                    tone={
                      v.status === "approved" || v.status === "posted"
                        ? "emerald"
                        : v.status === "failed"
                          ? "rose"
                          : "sky"
                    }
                  >
                    {v.status}
                  </Badge>
                </div>
                <div className="text-[12.5px] text-[var(--text-muted)] tabular-nums">
                  Phong cách:{" "}
                  <strong className="text-[var(--text-secondary)]">
                    {v.style_preset}
                  </strong>{" "}
                  • {v.aspect_ratio} •{" "}
                  {v.duration_s ? `${v.duration_s.toFixed(1)}s` : "Chưa xuất"}
                </div>
                {v.qc?.passed === true && (
                  <div className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--st-emerald-tx)]">
                    <CheckCircle2 className="w-3.5 h-3.5" /> Kiểm định kỹ thuật đạt chuẩn
                  </div>
                )}
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
