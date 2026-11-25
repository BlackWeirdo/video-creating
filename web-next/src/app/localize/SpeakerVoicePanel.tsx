"use client";

import React from "react";
import { Users } from "lucide-react";
import {
  LocalizeProject,
  SPEAKER_VOICE_OPTIONS,
  SpeakerEntry,
} from "@/app/localize/types";
import { Badge } from "@/components/ui/badge";
import {
  FieldLabel,
  SelectBox,
  SwitchToggle,
  TextInput,
} from "@/components/ui/form-controls";

export function SpeakerVoicePanel({
  project,
  canCloneVoice,
  onUpdateSpeaker,
  onToggleClone,
}: {
  project: LocalizeProject;
  canCloneVoice: boolean;
  onUpdateSpeaker: (spkId: string, patch: Partial<SpeakerEntry>) => Promise<void>;
  onToggleClone: (wantEnable: boolean) => Promise<void>;
}) {
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
    <div className="rounded-[12px] border border-[var(--border-subtle)] bg-[var(--bg-canvas)] p-3.5 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="inline-flex items-center gap-2 text-[13.5px] font-semibold text-[var(--text-primary)]">
          <Users className="w-4 h-4 text-[var(--c-icon)]" />
          <span>Phân vai Người nói ({speakerIds.length})</span>
        </div>

        {canCloneVoice && project.target_lang.startsWith("vi") && (
          <div className="inline-flex items-center gap-2">
            <SwitchToggle
              id="clone-voice-switch"
              checked={Boolean(project.clone_source_voice)}
              onCheckedChange={(checked) => void onToggleClone(checked)}
            />
            <label
              htmlFor="clone-voice-switch"
              className="text-[12.5px] font-semibold text-[var(--st-amber-tx)] cursor-pointer"
            >
              Nhân bản giọng gốc video nguồn (VieNeu CPU)
            </label>
          </div>
        )}
      </div>

      <div className="space-y-2">
        {speakerIds.map((spkId, idx) => {
          const spk = speakersMap[spkId] || {
            label: spkId,
            provider: "edge",
            voice_id: "vi-VN-HoaiMyNeural",
          };
          return (
            <div
              key={spkId}
              className="flex flex-wrap sm:flex-nowrap items-center gap-2 rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3 py-2"
            >
              <Badge tone={idx % 2 === 0 ? "cluster" : "sky"} className="font-mono">
                {spkId}
              </Badge>
              <TextInput
                aria-label={`Tên hiển thị cho ${spkId}`}
                defaultValue={spk.label}
                onBlur={(e) =>
                  void onUpdateSpeaker(spkId, { label: e.target.value })
                }
                className="min-h-[34px] py-1 sm:w-36"
              />
              <SelectBox
                aria-label={`Giọng đọc cho ${spkId}`}
                disabled={Boolean(project.clone_source_voice)}
                value={`${spk.provider}:${spk.voice_id}`}
                onChange={(e) => {
                  const [prov, vid] = e.target.value.split(":");
                  void onUpdateSpeaker(spkId, {
                    provider: prov,
                    voice_id: vid,
                  });
                }}
                className="min-h-[34px] py-1 flex-1"
              >
                {SPEAKER_VOICE_OPTIONS.map((opt) => (
                  <option
                    key={`${opt.provider}:${opt.voice_id}`}
                    value={`${opt.provider}:${opt.voice_id}`}
                  >
                    {opt.label}
                  </option>
                ))}
              </SelectBox>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function HardsubBoxPreview({
  project,
  onUpdateBox,
}: {
  project: LocalizeProject;
  onUpdateBox: (key: "x" | "y" | "w" | "h", value: number) => Promise<void>;
}) {
  const labels: Record<"x" | "y" | "w" | "h", string> = {
    x: "Lề trái X",
    y: "Đỉnh Y",
    w: "Rộng W",
    h: "Cao H",
  };

  return (
    <div className="rounded-[12px] border border-[var(--st-amber-bd)] bg-[var(--bg-elevated)] p-3.5 flex flex-wrap gap-4 items-center">
      <div
        aria-label="Mô phỏng khung dọc 9:16"
        className="relative w-24 h-44 rounded-[10px] border-2 border-[var(--border-strong)] bg-slate-950 overflow-hidden shrink-0"
      >
        <div className="absolute inset-0 flex items-center justify-center text-[11px] text-slate-400">
          Khung 9:16
        </div>
        <div
          className="absolute rounded border-2 border-amber-400 bg-amber-400/25"
          style={{
            left: `${Math.round((project.hardsub_box?.x ?? 0.06) * 100)}%`,
            top: `${Math.round((project.hardsub_box?.y ?? 0.74) * 100)}%`,
            width: `${Math.round((project.hardsub_box?.w ?? 0.88) * 100)}%`,
            height: `${Math.round((project.hardsub_box?.h ?? 0.16) * 100)}%`,
          }}
        />
      </div>

      <div className="flex-1 min-w-[220px] space-y-2">
        <div className="text-[13.5px] font-bold text-[var(--st-amber-tx)]">
          Vùng che / xóa phụ đề cứng ({project.ocr_cues?.length || 0} mốc chữ RapidOCR)
        </div>
        <p className="text-[12.5px] text-[var(--text-secondary)]">
          Khi có mốc OCR, hệ thống tự che mờ hoặc chạy LaMa Inpaint đúng tọa độ từng câu theo thời gian; hộp dưới đây là vùng bao tổng quát:
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {(["x", "y", "w", "h"] as const).map((k) => (
            <div key={k}>
              <FieldLabel htmlFor={`hardsub-${k}`}>{labels[k]}</FieldLabel>
              <TextInput
                id={`hardsub-${k}`}
                type="number"
                step="0.02"
                min={0}
                max={1}
                defaultValue={project.hardsub_box?.[k] ?? 0.1}
                onBlur={(e) => void onUpdateBox(k, Number(e.target.value))}
                className="min-h-[34px] py-1 tabular-nums"
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
