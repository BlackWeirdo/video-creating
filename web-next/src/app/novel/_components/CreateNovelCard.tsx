"use client";

import React, { useState } from "react";
import { Eye, Plus } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, ChannelVoiceOption, CharacterOption } from "@/lib/api";
import { BASE_NOVEL_VOICES, NovelProject } from "@/app/novel/types";
import { Card, SectionHeading } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  TextareaBox,
  TextInput,
} from "@/components/ui/form-controls";

export function CreateNovelCard({
  workspaceId,
  characters,
  channelVoices,
  onReload,
  onMessage,
  onError,
}: {
  workspaceId: number;
  characters: CharacterOption[];
  channelVoices: ChannelVoiceOption[];
  onReload: () => Promise<void>;
  onMessage: (m: string) => void;
  onError: (m: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [aspectRatio, setAspectRatio] = useState("9:16");
  const [characterId, setCharacterId] = useState<number>(0);
  const [visualSource, setVisualSource] = useState<"characters" | "muse_video">(
    "characters"
  );
  const [voiceId, setVoiceId] = useState("vi-VN-HoaiMyNeural");
  const [previewChapters, setPreviewChapters] = useState<
    Array<{ chapter_index: number; title: string; word_count: number }>
  >([]);

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
    onError("");
    onMessage("");
    try {
      const res = await apiFetch<{ project: NovelProject }>(
        "/api/v1/novels/projects",
        {
          method: "POST",
          body: JSON.stringify({
            workspace_id: workspaceId,
            title,
            source_text: sourceText,
            aspect_ratio: aspectRatio,
            character_id: characterId > 0 ? characterId : null,
            visual_source: visualSource,
            voice_id: voiceId,
          }),
        }
      );
      setTitle("");
      setSourceText("");
      setPreviewChapters([]);
      const m = `Đã tạo bộ truyện #${res.project.id} gồm ${res.project.total_chapters} chương.`;
      onMessage(m);
      toast.success(m);
      await onReload();
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Không thể tạo bộ truyện");
    }
  };

  return (
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
          <div>
            <FieldLabel htmlFor="nv-vis">Nguồn hình ảnh chương truyện</FieldLabel>
            <SelectBox
              id="nv-vis"
              value={visualSource}
              onChange={(e) =>
                setVisualSource(e.target.value as "characters" | "muse_video")
              }
            >
              <option value="characters">Nhân vật &amp; Ảnh chuyển động</option>
              <option value="muse_video">Clip Video Muse AI cho từng chương</option>
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
  );
}
