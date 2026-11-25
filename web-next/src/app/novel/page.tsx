"use client";

import React, { useCallback, useEffect, useState } from "react";
import { BookOpen, Eye, Play, Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import {
  apiFetch,
  ChannelVoiceOption,
  CharacterOption,
  useWorkspace,
} from "@/lib/api";
import { JobProgressBanner, useJobProgress } from "@/components/JobProgressBanner";
import { SimulationBadge } from "@/components/SimulationBadge";
import { PageHeader } from "@/components/vc/PageHeader";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  TextareaBox,
  TextInput,
} from "@/components/ui/form-controls";

interface NovelChapter {
  id: number;
  chapter_index: number;
  title: string;
  word_count: number;
  status: string;
  video_id: number | null;
  output_path: string;
  video_url: string;
}

interface NovelProject {
  id: number;
  title: string;
  aspect_ratio: string;
  style_preset: string;
  voice_id?: string;
  status: string;
  total_chapters: number;
  ready_chapters: number;
  chapters: NovelChapter[];
  simulation_flags?: string[];
}

const BASE_NOVEL_VOICES = [
  { value: "vi-VN-HoaiMyNeural", label: "Edge TTS: Hoài My (Nữ)" },
  { value: "vi-VN-NamMinhNeural", label: "Edge TTS: Nam Minh (Nam)" },
  { value: "vieneu:Mỹ Duyên", label: "VieNeu CPU: Mỹ Duyên (Nữ đọc truyện)" },
  { value: "vieneu:Đức Trí", label: "VieNeu CPU: Đức Trí (Nam đọc truyện)" },
  { value: "vieneu:Anh Khôi", label: "VieNeu CPU: Anh Khôi (Nam kể chuyện)" },
  { value: "vieneu:Trúc Ly", label: "VieNeu CPU: Trúc Ly (Nữ tự nhiên)" },
];

export default function NovelStudioPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [projects, setProjects] = useState<NovelProject[]>([]);
  const [characters, setCharacters] = useState<CharacterOption[]>([]);
  const [channelVoices, setChannelVoices] = useState<ChannelVoiceOption[]>([]);

  const [title, setTitle] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [aspectRatio, setAspectRatio] = useState("9:16");
  const [characterId, setCharacterId] = useState<number>(0);
  const [voiceId, setVoiceId] = useState("vi-VN-HoaiMyNeural");
  const [previewChapters, setPreviewChapters] = useState<
    Array<{ chapter_index: number; title: string; word_count: number }>
  >([]);
  const [renderingId, setRenderingId] = useState<number | null>(null);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [res, cRes, cvRes] = await Promise.all([
        apiFetch<{ projects: NovelProject[] }>(
          `/api/v1/novels/projects?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ characters: CharacterOption[] }>(
          `/api/v1/characters?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ channel_voices: ChannelVoiceOption[] }>(
          `/api/v1/channel-voices?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      setProjects(res.projects || []);
      setCharacters(cRes.characters || []);
      setChannelVoices(cvRes.channel_voices || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Studio Truyện");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const { job: activeJob, isRunning: jobRunning } = useJobProgress(activeJobId, {
    onStepChange: () => {
      void load();
    },
    onCompleted: () => {
      const done = `Đã xuất xong các chương cho bộ truyện #${renderingId ?? ""}.`;
      setMsg(done);
      toast.success(done);
      setRenderingId(null);
      void load();
    },
    onFailed: (j) => {
      setErr(j.error || "Lỗi xuất chương truyện");
      setRenderingId(null);
      void load();
    },
  });

  const voiceChoices = [
    ...channelVoices.map((cv) => ({
      value: cv.voice_token,
      label: `Giọng Kênh: ${cv.name} (${cv.speaker_name})`,
    })),
    ...BASE_NOVEL_VOICES,
  ];

  const previewSplit = async () => {
    if (!sourceText.trim()) return;
    const res = await apiFetch<{
      chapters: Array<{
        chapter_index: number;
        title: string;
        word_count: number;
      }>;
    }>("/api/v1/novels/split-preview", {
      method: "POST",
      body: JSON.stringify({
        source_text: sourceText,
        target_words_per_chapter: 140,
      }),
    });
    setPreviewChapters(res.chapters || []);
  };

  const createNovel = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ project: NovelProject }>(
        "/api/v1/novels/projects",
        {
          method: "POST",
          body: JSON.stringify({
            workspace_id: activeWorkspaceId,
            title,
            source_text: sourceText,
            aspect_ratio: aspectRatio,
            character_id: characterId > 0 ? characterId : null,
            voice_id: voiceId,
          }),
        }
      );
      setTitle("");
      setSourceText("");
      setPreviewChapters([]);
      const m = `Đã tạo bộ truyện #${res.project.id} gồm ${res.project.total_chapters} chương.`;
      setMsg(m);
      toast.success(m);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo bộ truyện");
    }
  };

  const renderProject = async (pid: number, force = false) => {
    setRenderingId(pid);
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ job_id: number }>(
        `/api/v1/novels/projects/${pid}/render`,
        {
          method: "POST",
          body: JSON.stringify({ sync: false, force }),
        }
      );
      setActiveJobId(res.job_id);
      const m = `Đã đưa các chương truyện #${pid} vào hàng đợi xuất video (Tác vụ #${res.job_id}).`;
      setMsg(m);
      toast.info(m);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi xuất chương truyện");
      setRenderingId(null);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <PageHeader
        icon={<BookOpen className="w-5 h-5" />}
        title="Truyện & Tiểu Thuyết Đa Chương → Video"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {projects.length} bộ truyện
          </Badge>
        }
        description="Tự động chia chương vừa thời lượng Shorts / YouTube, lồng tiếng đọc truyện tự nhiên và phục hồi thông minh từ đúng chương còn dở."
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
        label={renderingId ? `Bộ truyện #${renderingId}` : "Studio Truyện"}
        onDismiss={() => setActiveJobId(null)}
      />

      <Card tinted>
        <form onSubmit={createNovel} className="space-y-4">
          <SectionHeading>
            <Plus className="w-4 h-4 text-[var(--c-icon)]" /> Tạo Bộ Truyện / Tiểu Thuyết Mới
          </SectionHeading>

          <div className="grid md:grid-cols-4 gap-3.5">
            <div className="md:col-span-2">
              <FieldLabel htmlFor="nv-title">Tên bộ truyện</FieldLabel>
              <TextInput
                id="nv-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="VD: Bí Ẩn Tiệm Bạc Cổ Phố Hội"
              />
            </div>
            <div>
              <FieldLabel htmlFor="nv-voice">Giọng đọc kể chuyện</FieldLabel>
              <SelectBox
                id="nv-voice"
                value={voiceId}
                onChange={(e) => setVoiceId(e.target.value)}
              >
                {voiceChoices.map((v) => (
                  <option key={v.value} value={v.value}>
                    {v.label}
                  </option>
                ))}
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="nv-ratio">Tỷ lệ khung hình</FieldLabel>
              <SelectBox
                id="nv-ratio"
                value={aspectRatio}
                onChange={(e) => setAspectRatio(e.target.value)}
              >
                <option value="9:16">9:16 Dọc (Shorts / Reels)</option>
                <option value="16:9">16:9 Ngang (YouTube)</option>
                <option value="1:1">1:1 Vuông</option>
              </SelectBox>
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-3.5">
            <div>
              <FieldLabel htmlFor="nv-chr">Nhân vật dẫn truyện</FieldLabel>
              <SelectBox
                id="nv-chr"
                value={characterId}
                onChange={(e) => setCharacterId(Number(e.target.value))}
              >
                <option value={0}>Không gắn nhân vật dẫn truyện</option>
                {characters.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.voice_id})
                  </option>
                ))}
              </SelectBox>
            </div>
          </div>

          <div>
            <FieldLabel htmlFor="nv-text">
              Văn bản truyện gốc * (tự nhận diện tiêu đề Chương 1, Chương 2...)
            </FieldLabel>
            <TextareaBox
              id="nv-text"
              required
              rows={5}
              value={sourceText}
              onChange={(e) => setSourceText(e.target.value)}
              placeholder={
                "Chương 1: Mở đầu\nNội dung chương một...\n\nChương 2: Bước ngoặt\nNội dung chương hai..."
              }
            />
          </div>

          <div className="flex flex-wrap gap-2.5">
            <Button
              type="button"
              variant="secondary"
              onClick={() => void previewSplit()}
            >
              <Eye className="w-4 h-4 text-[var(--c-icon)]" /> Xem trước tách chương ({previewChapters.length})
            </Button>
            <Button type="submit">
              <Plus className="w-4 h-4" /> Tạo Dự Án Truyện
            </Button>
          </div>

          {previewChapters.length > 0 && (
            <div className="grid md:grid-cols-3 gap-2.5 pt-1">
              {previewChapters.map((c) => (
                <div
                  key={c.chapter_index}
                  className="rounded-[9px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3 py-2"
                >
                  <div className="truncate text-[13px] font-semibold text-[var(--text-primary)]">
                    {c.title}
                  </div>
                  <div className="text-[12px] text-[var(--text-muted)] tabular-nums">
                    {c.word_count} từ
                  </div>
                </div>
              ))}
            </div>
          )}
        </form>
      </Card>

      {projects.length === 0 ? (
        <EmptyState
          icon={<BookOpen className="w-5 h-5" />}
          title="Chưa có bộ truyện nào"
          description="Dán nội dung truyện vào biểu mẫu trên để tách chương và xuất video."
        />
      ) : (
        <div className="space-y-4">
          {projects.map((p) => (
            <Card key={p.id} className="space-y-3.5">
              <CardTitleRow>
                <div>
                  <h2 className="text-[15.5px] font-bold text-[var(--text-primary)]">
                    #{p.id} — {p.title}
                  </h2>
                  <div className="text-[12.5px] text-[var(--text-muted)] tabular-nums">
                    {p.ready_chapters}/{p.total_chapters} chương hoàn tất •{" "}
                    {p.aspect_ratio} •{" "}
                    <strong className="text-[var(--c-tx)]">{p.status}</strong>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    disabled={jobRunning && renderingId === p.id}
                    onClick={() => void renderProject(p.id, false)}
                  >
                    <Play className="w-3.5 h-3.5" />{" "}
                    {jobRunning && renderingId === p.id
                      ? "Đang xuất..."
                      : "Xuất tiếp chương còn thiếu"}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    disabled={jobRunning && renderingId === p.id}
                    onClick={() => void renderProject(p.id, true)}
                  >
                    <RefreshCw className="w-3.5 h-3.5" /> Xuất lại tất cả
                  </Button>
                </div>
              </CardTitleRow>

              <SimulationBadge flags={p.simulation_flags} />

              <div className="grid md:grid-cols-2 gap-3">
                {p.chapters.map((ch) => (
                  <div
                    key={ch.id}
                    className="rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5 space-y-2"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[13.5px] font-semibold text-[var(--text-primary)]">
                        {ch.title}
                      </span>
                      <Badge
                        tone={ch.status === "ready" ? "emerald" : "neutral"}
                      >
                        {ch.status}
                      </Badge>
                    </div>
                    {ch.video_url && (
                      <video
                        controls
                        preload="metadata"
                        src={ch.video_url}
                        className="w-full max-h-48 rounded-[8px] bg-black"
                      />
                    )}
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
