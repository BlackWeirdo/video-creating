"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Film, Play, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, CharacterOption } from "@/lib/api";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MuseStoryboard } from "@/app/muse/types";
import { SimulationBadge } from "@/components/SimulationBadge";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  SwitchToggle,
  TextareaBox,
  TextInput,
} from "@/components/ui/form-controls";

interface DraftSegment {
  prompt: string;
  duration_sec: number;
  caption: string;
}

export function StoryboardPanel({
  workspaceId,
  contentPolicy,
  storyboards,
  characters,
  onReload,
  onError,
}: {
  workspaceId: number;
  contentPolicy?: string;
  storyboards: MuseStoryboard[];
  characters: CharacterOption[];
  onReload: () => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [ratio, setRatio] = useState("9:16");
  const [continuity, setContinuity] = useState(true);
  const [voiceId, setVoiceId] = useState("muse:Glad Kite");
  const [charId, setCharId] = useState(0);
  const [segments, setSegments] = useState<DraftSegment[]>([
    { prompt: "", duration_sec: 8, caption: "" },
    { prompt: "", duration_sec: 8, caption: "" },
  ]);

  const isStrict = contentPolicy === "strict_footage";

  const updateSeg = (idx: number, patch: Partial<DraftSegment>) => {
    setSegments((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  };

  const { mutate: createSb, mutating } = useApiMutation(
    async () => {
      const sharedRefs = charId > 0 ? [{ type: "character", id: charId }] : [];
      const res = await apiFetch<{ storyboard: MuseStoryboard }>(
        "/api/v1/muse/storyboards",
        {
          method: "POST",
          body: JSON.stringify({
            workspace_id: workspaceId,
            title: title || "Storyboard Muse nối cảnh",
            ratio,
            continuity,
            narration: voiceId ? { voice_id: voiceId, lang: "vi" } : {},
            shared_refs: sharedRefs,
            segments,
          }),
        }
      );
      await apiFetch(`/api/v1/muse/storyboards/${res.storyboard.id}/generate`, {
        method: "POST",
      });
      void apiFetch("/api/v1/muse/dispatch", { method: "POST" }).catch(() => {});
      return res.storyboard;
    },
    {
      onError,
      onSuccess: async (sb) => {
        setTitle("");
        toast.success(`Đã khởi tạo & bắt đầu render Storyboard #${sb.id}!`);
        await onReload();
      },
    }
  );

  const runAction = async (url: string, msg: string, method = "POST") => {
    onError("");
    try {
      await apiFetch(url, { method });
      void apiFetch("/api/v1/muse/dispatch", { method: "POST" }).catch(() => {});
      toast.success(msg);
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Thao tác Storyboard lỗi");
    }
  };

  return (
    <div className="space-y-5">
      <Card tinted className="space-y-4">
        <SectionHeading>
          <Film className="w-4 h-4 text-[var(--c-icon)]" /> Dựng Video Dài Nhiều Cảnh Liền Mạch (Storyboard Frame-Bridging)
        </SectionHeading>

        {isStrict && (
          <div className="rounded-[10px] border border-[var(--st-amber-bd)] bg-[var(--st-amber-bg)] px-3.5 py-2 text-[12.5px] text-[var(--st-amber-tx)]">
            Workspace hiện tại đang ở chế độ <strong>Strict Footage</strong>. Hãy chuyển sang Workspace <strong>Hybrid Remix</strong> hoặc <strong>Full AI</strong> để dựng Storyboard AI.
          </div>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void createSb();
          }}
          className="space-y-4"
        >
          <div className="grid md:grid-cols-4 gap-3.5">
            <div className="md:col-span-2">
              <FieldLabel htmlFor="sb-title">Tiêu đề Storyboard *</FieldLabel>
              <TextInput
                id="sb-title"
                required
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="VD: Hành trình chế tác thủ công 3 phân cảnh"
              />
            </div>
            <div>
              <FieldLabel htmlFor="sb-ratio">Khung hình</FieldLabel>
              <SelectBox
                id="sb-ratio"
                value={ratio}
                onChange={(e) => setRatio(e.target.value)}
              >
                <option value="9:16">9:16 Dọc</option>
                <option value="16:9">16:9 Ngang</option>
                <option value="1:1">1:1 Vuông</option>
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="sb-voice">Giọng thuyết minh khi ghép</FieldLabel>
              <SelectBox
                id="sb-voice"
                value={voiceId}
                onChange={(e) => setVoiceId(e.target.value)}
              >
                <option value="muse:Glad Kite">Muse: Glad Kite (Nữ Việt)</option>
                <option value="muse:Kindhearted Jetty">Muse: Kindhearted Jetty (Nam Việt)</option>
                <option value="vi-VN-HoaiMyNeural">Edge: Hoài My (Nữ Việt)</option>
                <option value="">Không lồng tiếng</option>
              </SelectBox>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3.5 py-2.5">
            <div className="flex items-center gap-2.5">
              <SwitchToggle
                id="sb-cont"
                checked={continuity}
                onCheckedChange={setContinuity}
              />
              <label htmlFor="sb-cont" className="text-[13px] text-[var(--text-primary)] font-medium">
                Nối tiếp khung hình cuối (Frame-Bridging + giữ cùng hội thoại Muse)
              </label>
            </div>
            <div className="w-64">
              <SelectBox
                aria-label="Nhân vật xuyên suốt"
                value={charId}
                onChange={(e) => setCharId(Number(e.target.value))}
              >
                <option value={0}>Không gắn nhân vật chung</option>
                {characters.map((c) => (
                  <option key={c.id} value={c.id}>
                    Nhân vật: {c.name}
                  </option>
                ))}
              </SelectBox>
            </div>
          </div>

          <div className="space-y-2.5">
            {segments.map((seg, idx) => (
              <div
                key={idx}
                className="grid md:grid-cols-12 gap-2.5 rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3"
              >
                <div className="md:col-span-6">
                  <FieldLabel htmlFor={`sb-p-${idx}`}>Cảnh #{idx + 1} — Prompt *</FieldLabel>
                  <TextareaBox
                    id={`sb-p-${idx}`}
                    required
                    rows={2}
                    value={seg.prompt}
                    onChange={(e) => updateSeg(idx, { prompt: e.target.value })}
                    placeholder="Mô tả hành động và bối cảnh phân cảnh..."
                  />
                </div>
                <div className="md:col-span-4">
                  <FieldLabel htmlFor={`sb-c-${idx}`}>Lời đọc / Phụ đề cảnh #{idx + 1}</FieldLabel>
                  <TextareaBox
                    id={`sb-c-${idx}`}
                    rows={2}
                    value={seg.caption}
                    onChange={(e) => updateSeg(idx, { caption: e.target.value })}
                    placeholder="Câu thoại khớp phân cảnh..."
                  />
                </div>
                <div className="md:col-span-2 flex flex-col justify-between">
                  <div>
                    <FieldLabel htmlFor={`sb-d-${idx}`}>Giây</FieldLabel>
                    <TextInput
                      id={`sb-d-${idx}`}
                      type="number"
                      min={4}
                      max={15}
                      value={seg.duration_sec}
                      onChange={(e) =>
                        updateSeg(idx, { duration_sec: Number(e.target.value) })
                      }
                      className="tabular-nums"
                    />
                  </div>
                  {segments.length > 1 && (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setSegments((prev) => prev.filter((_, i) => i !== idx))
                      }
                    >
                      <Trash2 className="w-3.5 h-3.5" /> Xóa cảnh
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-2.5">
            <Button
              type="button"
              variant="secondary"
              onClick={() =>
                setSegments((prev) => [
                  ...prev,
                  { prompt: "", duration_sec: 8, caption: "" },
                ])
              }
            >
              <Plus className="w-4 h-4" /> Thêm phân cảnh
            </Button>
            <Button type="submit" disabled={mutating || isStrict}>
              <Play className="w-4 h-4" />{" "}
              {mutating ? "Đang khởi tạo..." : `Tạo & Render ${segments.length} Cảnh`}
            </Button>
          </div>
        </form>
      </Card>

      <Card className="space-y-3.5">
        <SectionHeading>Danh sách Storyboard ({storyboards.length})</SectionHeading>
        {storyboards.length === 0 ? (
          <EmptyState
            icon={<Film className="w-5 h-5" />}
            title="Chưa có Storyboard nhiều cảnh nào"
            description="Thêm các phân cảnh ở trên để Muse tự động nối khung cuối thành video dài có phụ đề & lồng tiếng."
          />
        ) : (
          <div className="space-y-3">
            {storyboards.map((sb) => (
              <div
                key={sb.id}
                className="rounded-[12px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-4 space-y-3"
              >
                <CardTitleRow>
                  <div className="flex flex-wrap items-center gap-2">
                    <strong className="text-[14.5px] text-[var(--text-primary)]">
                      #{sb.id} — {sb.title}
                    </strong>
                    <Badge tone="cluster">{sb.status}</Badge>
                    <Badge tone="neutral">
                      {sb.continuity ? "Nối khung liên tục" : "Song song độc lập"}
                    </Badge>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={() =>
                        void runAction(
                          `/api/v1/muse/storyboards/${sb.id}/generate`,
                          `Đã tiếp tục tạo cảnh cho Storyboard #${sb.id}`
                        )
                      }
                    >
                      <Play className="w-3.5 h-3.5" /> Render cảnh chờ
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="emerald"
                      onClick={() =>
                        void runAction(
                          `/api/v1/muse/storyboards/${sb.id}/assemble`,
                          `Đã ghép xong video cho Storyboard #${sb.id}`
                        )
                      }
                    >
                      Ghép Video MP4
                    </Button>
                    {sb.output_video_id && (
                      <Button asChild size="sm">
                        <Link href="/approval">Xem Video #{sb.output_video_id} →</Link>
                      </Button>
                    )}
                  </div>
                </CardTitleRow>

                <SimulationBadge flags={sb.simulation_flags} />

                <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
                  {sb.segments.map((seg) => (
                    <div
                      key={seg.id}
                      className="rounded-[9px] border border-[var(--border-subtle)] bg-[var(--bg-card)] p-2.5 text-[12.5px] space-y-1.5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-[var(--text-primary)]">
                          Cảnh #{seg.idx + 1} ({seg.duration_sec}s)
                        </span>
                        <Badge tone={seg.status === "succeeded" ? "emerald" : "neutral"}>
                          {seg.status}
                        </Badge>
                      </div>
                      <p className="line-clamp-2 text-[var(--text-secondary)]">
                        {seg.prompt}
                      </p>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          void runAction(
                            `/api/v1/muse/storyboards/${sb.id}/segments/${seg.idx}/regenerate`,
                            `Đã xếp tạo lại Cảnh #${seg.idx + 1}`
                          )
                        }
                      >
                        <RefreshCw className="w-3 h-3" /> Tạo lại cảnh
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
