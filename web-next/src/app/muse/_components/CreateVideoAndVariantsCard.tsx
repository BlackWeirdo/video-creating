"use client";

import React, { useState } from "react";
import { Layers, Sparkles, Upload } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, CharacterOption } from "@/lib/api";
import { useApiMutation } from "@/hooks/useApiMutation";
import type {
  MuseCombo,
  MuseModelOption,
  MuseRefDescriptor,
  MuseTask,
} from "@/app/muse/types";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  SwitchToggle,
  TextareaBox,
  TextInput,
} from "@/components/ui/form-controls";

export function CreateVideoAndVariantsCard({
  workspaceId,
  contentPolicy,
  capacity,
  models,
  combos,
  characters,
  products,
  onCreated,
  onError,
}: {
  workspaceId: number;
  contentPolicy?: string;
  capacity: number;
  models: MuseModelOption[];
  combos: MuseCombo[];
  characters: CharacterOption[];
  products: Array<{ id: number; name: string }>;
  onCreated: () => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState("muse-video");
  const [duration, setDuration] = useState(8);
  const [ratio, setRatio] = useState("9:16");
  const [variants, setVariants] = useState(1);
  const [charId, setCharId] = useState(0);
  const [prodId, setProdId] = useState(0);
  const [uploadedRef, setUploadedRef] = useState<string>("");
  const [hasRealFace, setHasRealFace] = useState(false);
  const [faceConsent, setFaceConsent] = useState(false);
  const [uploading, setUploading] = useState(false);

  const isStrict = contentPolicy === "strict_footage";
  const videoModels = [
    { value: "muse-video", label: "muse-video (Mặc định Pool)" },
    ...models
      .filter((m) => m.kind === "video" && m.id !== "muse-video")
      .map((m) => ({ value: m.id, label: m.id })),
    ...combos
      .filter((c) => !c.kind || c.kind === "video")
      .map((c) => ({
        value: c.name,
        label: `Combo: ${c.name} (${c.strategy})`,
      })),
  ];

  const handleUploadRef = async (file: File | null) => {
    if (!file) return;
    setUploading(true);
    onError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("workspace_id", String(workspaceId));
      const res = await apiFetch<{ upload_id: string }>("/api/v1/muse/refs/upload", {
        method: "POST",
        body: fd,
      });
      setUploadedRef(res.upload_id);
      toast.success("Đã tải tệp tham chiếu lên hàng chờ Muse.");
    } catch (err) {
      onError(err instanceof Error ? err.message : "Lỗi tải tệp tham chiếu");
    } finally {
      setUploading(false);
    }
  };

  const { mutate: submitTasks, mutating } = useApiMutation(
    async () => {
      const refs: MuseRefDescriptor[] = [];
      if (charId > 0) {
        refs.push({ type: "character", id: charId });
      }
      if (prodId > 0 && !isStrict) {
        refs.push({ type: "product", id: prodId });
      }
      if (uploadedRef) {
        refs.push({
          type: "upload",
          upload_id: uploadedRef,
          real_face: hasRealFace,
          face_consent_confirmed: faceConsent,
        });
      }
      const res = await apiFetch<{ tasks: MuseTask[] }>("/api/v1/muse/tasks", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId,
          kind: "video",
          model,
          prompt,
          duration,
          ratio,
          variants,
          refs,
        }),
      });
      void apiFetch("/api/v1/muse/dispatch", { method: "POST" }).catch(() => {});
      return res.tasks;
    },
    {
      onError,
      onSuccess: async (tasks) => {
        setPrompt("");
        setUploadedRef("");
        toast.success(`Đã xếp ${tasks.length} tác vụ video Muse vào bộ điều phối đa luồng!`);
        await onCreated();
      },
    }
  );

  return (
    <Card tinted className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SectionHeading>
          <Sparkles className="w-4 h-4 text-[var(--c-icon)]" /> Tạo Video Muse &amp; Render Đa Biến Thể Song Song
        </SectionHeading>
        <Badge tone="cluster" className="tabular-nums">
          Năng lực song song hiện tại: {Math.max(1, capacity)} luồng
        </Badge>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submitTasks();
        }}
        className="space-y-4"
      >
        <div>
          <FieldLabel htmlFor="ms-prompt">
            Mô tả cảnh quay (Prompt) * — khuyến nghị rõ chủ thể, chuyển động camera &amp; ánh sáng
          </FieldLabel>
          <TextareaBox
            id="ms-prompt"
            required
            rows={3}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="VD: Cận cảnh bàn trà gỗ óc chó dưới nắng mai, khói trà bay nhẹ, máy quay dolly chậm 4K điện ảnh..."
          />
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
          <div>
            <FieldLabel htmlFor="ms-model">Model / Combo Tài khoản</FieldLabel>
            <SelectBox
              id="ms-model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            >
              {videoModels.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </SelectBox>
          </div>

          <div>
            <FieldLabel htmlFor="ms-dur">Thời lượng yêu cầu (giây)</FieldLabel>
            <SelectBox
              id="ms-dur"
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
            >
              <option value={6}>6 giây (Ổn định nhất)</option>
              <option value={8}>8 giây (Tiêu chuẩn)</option>
              <option value={10}>10 giây</option>
              <option value={15}>15 giây (Có thể dừng sớm)</option>
              <option value={30}>30 giây (Khuyên dùng Storyboard)</option>
            </SelectBox>
          </div>

          <div>
            <FieldLabel htmlFor="ms-ratio">Khung hình</FieldLabel>
            <SelectBox
              id="ms-ratio"
              value={ratio}
              onChange={(e) => setRatio(e.target.value)}
            >
              <option value="9:16">9:16 Dọc (TikTok / Shorts)</option>
              <option value="16:9">16:9 Ngang (YouTube)</option>
              <option value="1:1">1:1 Vuông</option>
              <option value="3:4">3:4 Chân dung</option>
              <option value="4:3">4:3 Cổ điển</option>
            </SelectBox>
          </div>

          <div>
            <FieldLabel htmlFor="ms-variants">Số biến thể chạy song song</FieldLabel>
            <SelectBox
              id="ms-variants"
              value={variants}
              onChange={(e) => setVariants(Number(e.target.value))}
            >
              {[1, 2, 3, 4, 6, 8].map((n) => (
                <option key={n} value={n}>
                  {n} biến thể {n > 1 ? "(Đa luồng)" : ""}
                </option>
              ))}
            </SelectBox>
          </div>
        </div>

        <div className="grid md:grid-cols-3 gap-3.5 rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5">
          <div>
            <FieldLabel htmlFor="ms-chr">Tham chiếu Nhân vật</FieldLabel>
            <SelectBox
              id="ms-chr"
              value={charId}
              onChange={(e) => setCharId(Number(e.target.value))}
            >
              <option value={0}>Không gắn nhân vật</option>
              {characters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </SelectBox>
          </div>

          <div>
            <FieldLabel htmlFor="ms-prd">
              Tham chiếu Sản phẩm {isStrict ? "(Khóa ở Strict Footage)" : ""}
            </FieldLabel>
            <SelectBox
              id="ms-prd"
              disabled={isStrict}
              value={prodId}
              onChange={(e) => setProdId(Number(e.target.value))}
            >
              <option value={0}>Không gắn ảnh sản phẩm</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </SelectBox>
          </div>

          <div>
            <FieldLabel htmlFor="ms-upload">
              Tệp tham chiếu ngoài (Ảnh ≤20MB / Video ≤40MB)
            </FieldLabel>
            <div className="flex items-center gap-2">
              <TextInput
                id="ms-upload"
                type="file"
                accept=".png,.jpg,.jpeg,.webp,.mp4,.mov,.webm"
                disabled={uploading}
                onChange={(e) => void handleUploadRef(e.target.files?.[0] || null)}
              />
            </div>
            {uploadedRef && (
              <div className="mt-1 text-[11.5px] text-[var(--st-emerald-tx)]">
                Đã đính kèm: {uploadedRef}
              </div>
            )}
          </div>

          {uploadedRef && (
            <div className="md:col-span-3 flex flex-wrap items-center gap-4 pt-1">
              <div className="flex items-center gap-2">
                <SwitchToggle
                  id="ms-face"
                  checked={hasRealFace}
                  onCheckedChange={setHasRealFace}
                />
                <label htmlFor="ms-face" className="text-[12.5px] text-[var(--text-secondary)]">
                  Tệp có khuôn mặt người thật
                </label>
              </div>
              {hasRealFace && (
                <div className="flex items-center gap-2">
                  <SwitchToggle
                    id="ms-face-ok"
                    checked={faceConsent}
                    onCheckedChange={setFaceConsent}
                  />
                  <label
                    htmlFor="ms-face-ok"
                    className="text-[12.5px] font-medium text-[var(--st-amber-tx)]"
                  >
                    Tôi xác nhận đã có sự đồng ý của người trong ảnh/video
                  </label>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            type="submit"
            disabled={mutating || uploading || (hasRealFace && !faceConsent)}
          >
            <Layers className="w-4 h-4" />{" "}
            {mutating
              ? "Đang gửi..."
              : variants > 1
                ? `Tạo ${variants} Video Song Song`
                : "Tạo Video Muse"}
          </Button>
          {uploading && (
            <span className="inline-flex items-center gap-1.5 text-[12.5px] text-[var(--text-muted)]">
              <Upload className="w-3.5 h-3.5" /> Đang tải tệp tham chiếu...
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}
