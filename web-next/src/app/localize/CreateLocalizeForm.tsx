"use client";

import React, { useEffect, useState } from "react";
import { Upload } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, Workspace } from "@/lib/api";
import { LocalizeProject } from "@/app/localize/types";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  SwitchToggle,
  TextInput,
} from "@/components/ui/form-controls";

export function CreateLocalizeForm({
  workspaceId,
  wsPolicy,
  onCreated,
  onError,
  onMessage,
}: {
  workspaceId: number;
  wsPolicy: Workspace["content_policy"];
  onCreated: (newId: number) => Promise<void>;
  onError: (msg: string) => void;
  onMessage: (msg: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [mode, setMode] =
    useState<LocalizeProject["mode"]>("intl_export");
  const [sourceMediaPath, setSourceMediaPath] = useState("");
  const [sourceLang, setSourceLang] = useState("auto");
  const [targetLang, setTargetLang] = useState("vi");
  const [hardsubMode, setHardsubMode] =
    useState<LocalizeProject["hardsub_mode"]>("blur_bar");
  const [whisperSize, setWhisperSize] = useState<"small" | "medium">("small");
  const [translationStyle, setTranslationStyle] = useState<
    "natural_tiktok" | "literal"
  >("natural_tiktok");
  const [stylePreset, setStylePreset] = useState("tiktok_karaoke");
  const [mirror, setMirror] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (wsPolicy === "strict_footage") setMode("intl_export");
    else if (wsPolicy === "hybrid_remix") setMode("hybrid_remix");
    else if (wsPolicy === "full_ai") setMode("reup_vi");
  }, [wsPolicy]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    onError("");
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch("/api/v1/localize/upload", {
      method: "POST",
      body: fd,
    });
    const data = await resp.json();
    if (!resp.ok) {
      onError(data.detail || "Tải video thất bại");
      return;
    }
    setSourceMediaPath(data.source_media_path || "");
    const m = `Đã tải video nguồn: ${data.source_media_path}`;
    onMessage(m);
    toast.success(m);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    onError("");
    onMessage("");
    setSubmitting(true);
    try {
      const res = await apiFetch<{ project: LocalizeProject }>(
        "/api/v1/localize/projects",
        {
          method: "POST",
          body: JSON.stringify({
            workspace_id: workspaceId,
            title,
            mode,
            source_media_path: sourceMediaPath,
            source_lang: sourceLang,
            target_lang: targetLang,
            hardsub_mode: hardsubMode,
            whisper_size: whisperSize,
            translation_style: translationStyle,
            style_preset: stylePreset,
            anti_dup: { mirror, zoom: 1.04, color_eq: true },
          }),
        }
      );
      setTitle("");
      const m = `Đã tạo dự án Việt hóa / Remix #${res.project.id}.`;
      onMessage(m);
      toast.success(m);
      await onCreated(res.project.id);
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Không thể tạo dự án");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card tinted>
      <form onSubmit={handleCreate} className="space-y-4">
        <CardTitleRow>
          <SectionHeading>Tạo dự án Việt hóa / Remix mới</SectionHeading>
          <span className="text-[12px] text-[var(--text-muted)]">
            Hỗ trợ Douyin, TikTok, YouTube Shorts (.mp4, .mov, .mkv, .webm)
          </span>
        </CardTitleRow>

        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-3">
          <div>
            <FieldLabel htmlFor="loc-title">Tên dự án *</FieldLabel>
            <TextInput
              id="loc-title"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="VD: Việt hóa Douyin trang sức bạc"
            />
          </div>
          <div>
            <FieldLabel htmlFor="loc-mode">Chế độ sản xuất</FieldLabel>
            <SelectBox
              id="loc-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as LocalizeProject["mode"])}
            >
              <option value="reup_vi" disabled={wsPolicy !== "full_ai"}>
                Việt hóa toàn phần (Full AI)
              </option>
              <option value="hybrid_remix" disabled={wsPolicy === "strict_footage"}>
                Hybrid Remix (Tráo Shot thật)
              </option>
              <option value="intl_export">
                Quốc tế hóa ngược (EN / ZH / JA / KO)
              </option>
            </SelectBox>
          </div>
          <div>
            <FieldLabel htmlFor="loc-src-lang">Ngôn ngữ gốc</FieldLabel>
            <SelectBox
              id="loc-src-lang"
              value={sourceLang}
              onChange={(e) => setSourceLang(e.target.value)}
            >
              <option value="auto">Tự nhận diện (Trung / Anh)</option>
              <option value="zh">Tiếng Trung (Douyin / XHS)</option>
              <option value="en">Tiếng Anh (TikTok / YT)</option>
              <option value="vi">Tiếng Việt</option>
            </SelectBox>
          </div>
          <div>
            <FieldLabel htmlFor="loc-tgt-lang">Ngôn ngữ đích</FieldLabel>
            <SelectBox
              id="loc-tgt-lang"
              value={targetLang}
              onChange={(e) => setTargetLang(e.target.value)}
            >
              <option value="vi">Tiếng Việt (vi)</option>
              <option value="en">English (en)</option>
              <option value="zh">Tiếng Trung (zh)</option>
              <option value="ja">Tiếng Nhật (ja)</option>
              <option value="ko">Tiếng Hàn (ko)</option>
            </SelectBox>
          </div>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-3">
          <div>
            <FieldLabel htmlFor="loc-hardsub">Xử lý chữ cứng gốc</FieldLabel>
            <SelectBox
              id="loc-hardsub"
              value={hardsubMode}
              onChange={(e) =>
                setHardsubMode(e.target.value as LocalizeProject["hardsub_mode"])
              }
            >
              <option value="blur_bar">Quét OCR → Làm mờ đúng vị trí</option>
              <option value="ocr_inpaint">LaMa ONNX xóa chữ chất lượng cao</option>
              <option value="crop_frame">Cắt viền khung hình mất chữ</option>
              <option value="none">Giữ nguyên khung hình</option>
            </SelectBox>
          </div>
          <div>
            <FieldLabel htmlFor="loc-trans-style">Phong cách dịch</FieldLabel>
            <SelectBox
              id="loc-trans-style"
              value={translationStyle}
              onChange={(e) =>
                setTranslationStyle(e.target.value as "natural_tiktok" | "literal")
              }
            >
              <option value="natural_tiktok">
                Tự nhiên kiểu TikTok Việt (Khớp nhịp)
              </option>
              <option value="literal">Sát nghĩa nguyên bản</option>
            </SelectBox>
          </div>
          <div>
            <FieldLabel htmlFor="loc-whisper">Mô hình chép lời CPU</FieldLabel>
            <SelectBox
              id="loc-whisper"
              value={whisperSize}
              onChange={(e) =>
                setWhisperSize(e.target.value as "small" | "medium")
              }
            >
              <option value="small">Whisper Small (Nhanh, mặc định)</option>
              <option value="medium">Whisper Medium (Chính xác cao tiếng Trung)</option>
            </SelectBox>
          </div>
          <div>
            <FieldLabel htmlFor="loc-style">Kiểu phụ đề xuất ra</FieldLabel>
            <SelectBox
              id="loc-style"
              value={stylePreset}
              onChange={(e) => setStylePreset(e.target.value)}
            >
              <option value="tiktok_karaoke">TikTok Karaoke nổi bật từ</option>
              <option value="bilingual_stack">Phụ đề Song ngữ</option>
              <option value="box_highlight">Hộp chữ tương phản cao</option>
              <option value="neon_glow">Chữ phát sáng Neon</option>
            </SelectBox>
          </div>
        </div>

        <div className="grid md:grid-cols-3 gap-3 items-end">
          <div>
            <FieldLabel htmlFor="loc-media-path">Đường dẫn video nguồn</FieldLabel>
            <TextInput
              id="loc-media-path"
              value={sourceMediaPath}
              onChange={(e) => setSourceMediaPath(e.target.value)}
              placeholder="localize/uploads/..."
            />
          </div>

          <div>
            <span className="block text-[12.5px] font-medium text-[var(--text-secondary)] mb-1">
              Hoặc tải tệp từ máy tính
            </span>
            <label className="inline-flex w-full min-h-[38px] items-center justify-center gap-2 rounded-[8px] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 py-1.5 text-[13px] font-medium text-[var(--text-primary)] hover:border-[var(--c-bd)] cursor-pointer transition-colors">
              <Upload className="w-4 h-4 text-[var(--c-icon)]" />
              <span>Chọn tệp video (.mp4 / .mov)</span>
              <input
                type="file"
                accept=".mp4,.mov,.mkv,.webm"
                onChange={handleUpload}
                className="sr-only"
              />
            </label>
          </div>

          <div className="flex items-center justify-between gap-3">
            <div className="inline-flex items-center gap-2">
              <SwitchToggle
                id="loc-mirror"
                checked={mirror}
                onCheckedChange={setMirror}
              />
              <label
                htmlFor="loc-mirror"
                className="text-[13px] text-[var(--text-secondary)] cursor-pointer"
              >
                Lật gương chống trùng
              </label>
            </div>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Đang tạo..." : "Tạo Dự Án"}
            </Button>
          </div>
        </div>
      </form>
    </Card>
  );
}
