"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Music, Palette, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { PageHeader } from "@/components/vc/PageHeader";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  SwitchToggle,
  TextInput,
} from "@/components/ui/form-controls";

interface StylePreset {
  id: string;
  name: string;
  subtitle_style: string;
  font_size: number;
  highlight_color: string;
  position: string;
  ducking_enabled: boolean;
  music_volume: number;
  intro_text: string;
  outro_text: string;
  is_builtin: boolean;
}

interface AudioAsset {
  id: number;
  kind: string;
  title: string;
  duration_s: number;
  media_url: string | null;
}

export default function VideoStylePage() {
  const { activeWorkspaceId } = useWorkspace();
  const [styles, setStyles] = useState<StylePreset[]>([]);
  const [assets, setAssets] = useState<AudioAsset[]>([]);
  const [name, setName] = useState("");
  const [subStyle, setSubStyle] = useState("karaoke_highlight");
  const [highlightColor, setHighlightColor] = useState("#FFE082");
  const [introText, setIntroText] = useState("");
  const [outroText, setOutroText] = useState("");
  const [ducking, setDucking] = useState(true);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioKind, setAudioKind] = useState<"music" | "sfx">("music");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [sRes, aRes] = await Promise.all([
        apiFetch<{ styles: StylePreset[] }>(
          `/api/v1/styles?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ assets: AudioAsset[] }>(
          `/api/v1/assets?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      setStyles(sRes.styles || []);
      setAssets(aRes.assets || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Phong cách & Âm thanh");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreateStyle = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    try {
      await apiFetch("/api/v1/styles", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          name,
          subtitle_style: subStyle,
          highlight_color: highlightColor,
          intro_text: introText,
          outro_text: outroText,
          ducking_enabled: ducking,
        }),
      });
      setName("");
      setIntroText("");
      setOutroText("");
      toast.success("Đã lưu mẫu phong cách phụ đề mới.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo mẫu phong cách");
    }
  };

  const handleDeleteStyle = async (id: string) => {
    await apiFetch(`/api/v1/styles/${id}`, { method: "DELETE" });
    toast.success("Đã xóa mẫu phong cách.");
    await load();
  };

  const handleUploadAsset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!audioFile) return;
    const fd = new FormData();
    fd.append("file", audioFile);
    fd.append("workspace_id", String(activeWorkspaceId));
    fd.append("kind", audioKind);
    await apiFetch("/api/v1/assets/upload", { method: "POST", body: fd });
    setAudioFile(null);
    toast.success("Đã nạp tệp âm thanh mới.");
    await load();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        icon={<Palette className="w-5 h-5" />}
        title="Phong Cách Phụ Đề & Thư Viện Âm Thanh"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {styles.length} mẫu chữ • {assets.length} tệp âm thanh
          </Badge>
        }
        description="Thiết kế 6 kiểu phụ đề nhảy chữ Karaoke, tự động hạ nhỏ nhạc nền khi có giọng đọc (Auto-Ducking) và chuẩn hóa âm lượng -14 LUFS."
      />

      {err && (
        <div
          role="alert"
          className="rounded-[11px] border border-[var(--st-rose-bd)] bg-[var(--st-rose-bg)] px-4 py-2.5 text-[13px] text-[var(--st-rose-tx)]"
        >
          {err}
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        <Card tinted>
          <form onSubmit={handleCreateStyle} className="space-y-3.5">
            <SectionHeading>
              <Plus className="w-4 h-4 text-[var(--c-icon)]" /> Tạo Mẫu Phong Cách Mới
            </SectionHeading>

            <div>
              <FieldLabel htmlFor="st-name">Tên mẫu phong cách *</FieldLabel>
              <TextInput
                id="st-name"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="VD: Karaoke Vàng Nổi Bật"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <FieldLabel htmlFor="st-sub">Kiểu hiển thị phụ đề</FieldLabel>
                <SelectBox
                  id="st-sub"
                  value={subStyle}
                  onChange={(e) => setSubStyle(e.target.value)}
                >
                  <option value="karaoke_highlight">Karaoke tô màu từng từ</option>
                  <option value="tiktok_pop">Chữ nảy nhịp điệu TikTok</option>
                  <option value="box_highlight">Hộp nền đậm tương phản</option>
                  <option value="neon_glow">Phát sáng Neon hai lớp</option>
                  <option value="minimal_bottom">Tối giản tinh tế</option>
                  <option value="bilingual">Song ngữ hai dòng</option>
                </SelectBox>
              </div>
              <div>
                <FieldLabel htmlFor="st-color">Mã màu nhấn từ khóa</FieldLabel>
                <TextInput
                  id="st-color"
                  value={highlightColor}
                  onChange={(e) => setHighlightColor(e.target.value)}
                  className="font-mono"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <FieldLabel htmlFor="st-intro">Chữ mở đầu (tùy chọn)</FieldLabel>
                <TextInput
                  id="st-intro"
                  value={introText}
                  onChange={(e) => setIntroText(e.target.value)}
                />
              </div>
              <div>
                <FieldLabel htmlFor="st-outro">Chữ kết thúc (tùy chọn)</FieldLabel>
                <TextInput
                  id="st-outro"
                  value={outroText}
                  onChange={(e) => setOutroText(e.target.value)}
                />
              </div>
            </div>

            <div className="flex items-center gap-2.5">
              <SwitchToggle
                id="st-duck"
                checked={ducking}
                onCheckedChange={setDucking}
              />
              <label
                htmlFor="st-duck"
                className="text-[13px] text-[var(--text-secondary)] cursor-pointer"
              >
                Tự động hạ nhỏ nhạc nền khi có lời thoại
              </label>
            </div>

            <Button type="submit">Lưu Mẫu Phong Cách</Button>
          </form>
        </Card>

        <Card className="space-y-3.5">
          <form onSubmit={handleUploadAsset} className="space-y-3.5">
            <SectionHeading className="tabular-nums">
              <Music className="w-4 h-4 text-[var(--c-icon)]" /> Nhạc Nền &amp; Hiệu Ứng Âm Thanh ({assets.length})
            </SectionHeading>

            <div className="grid sm:grid-cols-2 gap-3">
              <div>
                <FieldLabel htmlFor="au-kind">Phân loại âm thanh</FieldLabel>
                <SelectBox
                  id="au-kind"
                  value={audioKind}
                  onChange={(e) =>
                    setAudioKind(e.target.value as "music" | "sfx")
                  }
                >
                  <option value="music">Nhạc nền (BGM)</option>
                  <option value="sfx">Hiệu ứng chuyển cảnh (SFX)</option>
                </SelectBox>
              </div>
              <div>
                <FieldLabel htmlFor="au-file">Chọn tệp âm thanh</FieldLabel>
                <input
                  id="au-file"
                  type="file"
                  accept=".mp3,.wav,.m4a,.aac,.ogg,.flac"
                  onChange={(e) => setAudioFile(e.target.files?.[0] || null)}
                  className="block w-full text-[12.5px] text-[var(--text-secondary)] file:mr-2 file:rounded-md file:border file:border-[var(--border-strong)] file:bg-[var(--bg-elevated)] file:px-2.5 file:py-1.5 file:text-[12px] file:font-semibold file:text-[var(--text-primary)] file:cursor-pointer"
                />
              </div>
            </div>

            <Button type="submit" variant="emerald" disabled={!audioFile}>
              Tải lên Thư Viện
            </Button>
          </form>

          {assets.length > 0 && (
            <div className="space-y-2 max-h-48 overflow-y-auto pt-1">
              {assets.map((a) => (
                <div
                  key={a.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-[9px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3 py-2 text-[12.5px]"
                >
                  <span>
                    <Badge tone="sky" className="uppercase mr-2 text-[11px]">
                      {a.kind}
                    </Badge>
                    <strong className="text-[var(--text-primary)]">{a.title}</strong>{" "}
                    <span className="text-[var(--text-muted)] tabular-nums">
                      ({a.duration_s.toFixed(1)}s)
                    </span>
                  </span>
                  {a.media_url && (
                    <audio controls src={a.media_url} className="h-7 w-44" />
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        {styles.map((s) => (
          <Card key={s.id} className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <strong className="text-[14.5px] text-[var(--text-primary)]">
                {s.name}
              </strong>
              {!s.is_builtin ? (
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={`Xóa mẫu ${s.name}`}
                  onClick={() => void handleDeleteStyle(s.id)}
                >
                  <Trash2 className="w-4 h-4 text-rose-400" />
                </Button>
              ) : (
                <Badge tone="neutral">Có sẵn</Badge>
              )}
            </div>
            <div className="text-[12.5px] text-[var(--text-muted)]">
              Kiểu chữ:{" "}
              <strong className="text-[var(--c-tx)]">{s.subtitle_style}</strong>
            </div>
            <div className="flex items-center gap-2 text-[12.5px] text-[var(--text-muted)]">
              <span>Màu nhấn:</span>
              <span
                className="inline-block h-4 w-4 rounded-full border border-[var(--border-strong)]"
                style={{ backgroundColor: s.highlight_color }}
              />
              <span className="font-mono">{s.highlight_color}</span>
              <span>• Hạ nhạc: {s.ducking_enabled ? "Bật" : "Tắt"}</span>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
