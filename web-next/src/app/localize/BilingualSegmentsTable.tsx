"use client";

import React from "react";
import { AlertTriangle, Languages, Volume2 } from "lucide-react";
import {
  LocalizeProject,
  LocalizeSegment,
  ShotRow,
  SpeakerEntry,
} from "@/app/localize/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SelectBox, TextInput } from "@/components/ui/form-controls";
import { ModalDialog } from "@/components/ui/overlays";
import { EmptyState } from "@/components/vc/StatCard";

export function BilingualSegmentsTable({
  project,
  shots,
  previewAudioMap,
  previewLoadingKey,
  onUpdateSegment,
  onPreviewLine,
}: {
  project: LocalizeProject | null;
  shots: ShotRow[];
  previewAudioMap: Record<string, string>;
  previewLoadingKey: string | null;
  onUpdateSegment: (idx: number, patch: Partial<LocalizeSegment>) => Promise<void>;
  onPreviewLine: (idx: number) => Promise<void>;
}) {
  if (!project || project.segments.length === 0) {
    return (
      <EmptyState
        icon={<Languages className="w-5 h-5" />}
        title="Chưa có câu thoại nào được tách"
        description='Chọn một dự án ở cột trái và bấm "Tách lời & Dịch" để chạy MDX-Net, quét chữ cứng OCR, Faster-Whisper và dịch tự động.'
      />
    );
  }

  const speakersMap: Record<string, SpeakerEntry> =
    project.speaker_config?.speakers || {
      SPK_1: {
        label: "Người nói 1",
        provider: "edge",
        voice_id: "vi-VN-HoaiMyNeural",
      },
    };
  const speakerIds =
    Object.keys(speakersMap).length > 0 ? Object.keys(speakersMap) : ["SPK_1"];

  return (
    <div className="space-y-3">
      {project.segments.map((seg, idx) => {
        const pKey = `${project.id}:${idx}`;
        const audioUrl = previewAudioMap[pKey] || seg.preview_audio_url;
        const overBudget =
          (seg.syllable_count ?? 0) >
          Math.ceil((seg.syllable_budget ?? 99) * 1.25);

        return (
          <article
            key={idx}
            className="rounded-[12px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5 space-y-2.5 transition-colors hover:border-[var(--c-bd)]"
          >
            <div className="flex flex-wrap items-center justify-between gap-2 text-[12.5px]">
              <div className="flex flex-wrap items-center gap-2">
                <strong className="text-[var(--text-primary)] tabular-nums">
                  #{idx + 1} • {seg.start_s.toFixed(1)}s – {seg.end_s.toFixed(1)}s
                </strong>
                {seg.text_origin && (
                  <Badge tone="sky" className="uppercase text-[11px] px-2 py-0">
                    {seg.text_origin}
                  </Badge>
                )}
                <SelectBox
                  aria-label={`Chọn người nói cho câu #${idx + 1}`}
                  value={seg.speaker_id || "SPK_1"}
                  onChange={(e) =>
                    void onUpdateSegment(idx, { speaker_id: e.target.value })
                  }
                  className="w-auto min-h-[30px] py-0.5 px-2.5 text-[12px]"
                >
                  {speakerIds.map((sid) => (
                    <option key={sid} value={sid}>
                      {speakersMap[sid]?.label || sid}
                    </option>
                  ))}
                </SelectBox>
              </div>

              <div className="flex items-center gap-2">
                <Badge
                  tone={overBudget ? "amber" : "emerald"}
                  className="tabular-nums"
                >
                  {overBudget && <AlertTriangle className="w-3 h-3" />}
                  Âm tiết: {seg.syllable_count ?? "?"}/{seg.syllable_budget ?? "?"}
                </Badge>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={previewLoadingKey === pKey}
                  onClick={() => void onPreviewLine(idx)}
                >
                  <Volume2 className="w-3.5 h-3.5 text-[var(--c-icon)]" />
                  <span>
                    {previewLoadingKey === pKey ? "Đang đọc..." : "Nghe thử"}
                  </span>
                </Button>
              </div>
            </div>

            <div className="border-l-2 border-[var(--c-bd)] pl-2.5 text-[13px] text-[var(--text-muted)]">
              Gốc: {seg.source_text}
            </div>

            <div>
              <label
                htmlFor={`seg-trans-${project.id}-${idx}`}
                className="sr-only"
              >
                Lời dịch câu #{idx + 1}
              </label>
              <TextInput
                id={`seg-trans-${project.id}-${idx}`}
                key={`${project.id}-${idx}-${seg.translated_text}`}
                defaultValue={seg.translated_text}
                onBlur={(e) => {
                  if (e.target.value !== seg.translated_text) {
                    void onUpdateSegment(idx, { translated_text: e.target.value });
                  }
                }}
              />
            </div>

            {audioUrl && (
              <audio controls src={audioUrl} className="h-8 w-full max-w-sm" />
            )}

            {project.mode === "hybrid_remix" && (
              <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
                <label
                  htmlFor={`seg-shot-${project.id}-${idx}`}
                  className="font-semibold text-[var(--c-tx)]"
                >
                  Tráo Shot sản phẩm thật:
                </label>
                <SelectBox
                  id={`seg-shot-${project.id}-${idx}`}
                  value={seg.replace_shot_id || 0}
                  onChange={(e) =>
                    void onUpdateSegment(idx, {
                      replace_shot_id: Number(e.target.value),
                    })
                  }
                  className="min-h-[34px] py-1 flex-1"
                >
                  <option value={0}>
                    Giữ khung hình gốc (đã xử lý chữ cứng)
                  </option>
                  {shots.map((s) => (
                    <option key={s.id} value={s.id}>
                      Shot #{s.id} — {s.description || "Sản phẩm"}
                    </option>
                  ))}
                </SelectBox>
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}

export function VoiceCloneConsentModal({
  open,
  projectId,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  projectId: number | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => Promise<void>;
}) {
  return (
    <ModalDialog
      open={open}
      onOpenChange={onOpenChange}
      title={
        <span className="inline-flex items-center gap-2 text-[var(--st-amber-tx)]">
          <AlertTriangle className="w-5 h-5 shrink-0" />
          Xác nhận trách nhiệm Nhân bản Giọng gốc
        </span>
      }
      description="Nhân bản giọng người nói trong video nguồn có thể ảnh hưởng đến quyền nhân thân, bản quyền và chính sách của TikTok, YouTube, Facebook."
    >
      <ul className="list-disc list-inside text-[13px] text-[var(--text-secondary)] space-y-1.5 mb-5">
        <li>
          Mẫu giọng trích xuất chỉ lưu cục bộ trong dự án #{projectId}, không đưa vào thư viện chung.
        </li>
        <li>
          Thao tác bật và xuất video được ghi nhận vào nhật ký kiểm toán (<code>audit_log</code>).
        </li>
        <li>
          Người vận hành chịu hoàn toàn trách nhiệm pháp lý và bản quyền khi đăng tải.
        </li>
      </ul>
      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="secondary"
          onClick={() => onOpenChange(false)}
        >
          Hủy bỏ
        </Button>
        <Button type="button" variant="amber" onClick={() => void onConfirm()}>
          Tôi hiểu và chịu trách nhiệm — Bật nhân bản
        </Button>
      </div>
    </ModalDialog>
  );
}
