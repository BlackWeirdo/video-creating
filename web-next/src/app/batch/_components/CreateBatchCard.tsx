"use client";

import React, { useState } from "react";
import { Play } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import type { BatchRunRow, ProductOption } from "@/app/batch/types";
import { Card, SectionHeading } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  TextareaBox,
  TextInput,
} from "@/components/ui/form-controls";

export function CreateBatchCard({
  workspaceId,
  products,
  onCreated,
  onMessage,
  onError,
}: {
  workspaceId: number;
  products: ProductOption[];
  onCreated: (jobId: number) => Promise<void>;
  onMessage: (m: string) => void;
  onError: (m: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [sourceKind, setSourceKind] = useState<
    "products" | "prompts" | "trends"
  >("products");
  const [selectedProdIds, setSelectedProdIds] = useState<number[]>([]);
  const [promptsText, setPromptsText] = useState("");
  const [abCount, setAbCount] = useState(2);
  const [visualSource, setVisualSource] = useState<
    "workspace_shots" | "muse_video"
  >("workspace_shots");
  const [styleA, setStyleA] = useState("tiktok_karaoke");
  const [styleB, setStyleB] = useState("box_highlight");

  const createBatch = async (e: React.FormEvent) => {
    e.preventDefault();
    onError("");
    onMessage("");
    try {
      const items =
        sourceKind === "products"
          ? selectedProdIds
          : promptsText
              .split(/\r?\n/)
              .map((l) => l.trim())
              .filter(Boolean);
      const res = await apiFetch<{ batch: BatchRunRow; job_id: number }>(
        "/api/v1/batches",
        {
          method: "POST",
          body: JSON.stringify({
            workspace_id: workspaceId,
            title: title || `Chiến dịch ${sourceKind}`,
            source_kind: sourceKind,
            items,
            ab_count: abCount,
            visual_source: visualSource,
            style_presets: [styleA, styleB],
            sync: false,
          }),
        }
      );
      setTitle("");
      setPromptsText("");
      const m = `Đã khởi chạy lô #${res.batch.id} (Tác vụ #${res.job_id}).`;
      onMessage(m);
      toast.info(m);
      await onCreated(res.job_id);
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Không thể tạo lô sản xuất");
    }
  };

  return (
    <Card tinted>
      <form onSubmit={createBatch} className="space-y-4">
        <SectionHeading>Khởi Chạy Chiến Dịch Hàng Loạt Mới</SectionHeading>

        <div className="grid md:grid-cols-2 lg:grid-cols-5 gap-3.5">
          <div>
            <FieldLabel htmlFor="bt-title">Tên chiến dịch</FieldLabel>
            <TextInput
              id="bt-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="VD: Lô BST Hè 2026"
            />
          </div>
          <div>
            <FieldLabel htmlFor="bt-kind">Nguồn đầu vào</FieldLabel>
            <SelectBox
              id="bt-kind"
              value={sourceKind}
              onChange={(e) =>
                setSourceKind(
                  e.target.value as "products" | "prompts" | "trends"
                )
              }
            >
              <option value="products">Theo Sản phẩm trong Workspace</option>
              <option value="prompts">Theo danh sách Ý tưởng</option>
              <option value="trends">Theo mã Video Xu hướng</option>
            </SelectBox>
          </div>
          <div>
            <FieldLabel htmlFor="bt-vis">Nguồn cảnh quay</FieldLabel>
            <SelectBox
              id="bt-vis"
              value={visualSource}
              onChange={(e) =>
                setVisualSource(
                  e.target.value as "workspace_shots" | "muse_video"
                )
              }
            >
              <option value="workspace_shots">Kho Shot Workspace</option>
              <option value="muse_video">Clip Muse AI (Đa luồng)</option>
            </SelectBox>
          </div>
          <div>
            <FieldLabel htmlFor="bt-ab">Số lượng biến thể</FieldLabel>
            <SelectBox
              id="bt-ab"
              value={abCount}
              onChange={(e) => setAbCount(Number(e.target.value))}
            >
              <option value={1}>1 bản tiêu chuẩn (A)</option>
              <option value={2}>2 biến thể đối chứng (A / B)</option>
              <option value={3}>3 biến thể đối chứng (A / B / C)</option>
            </SelectBox>
          </div>
          <div>
            <FieldLabel htmlFor="bt-style-a">Cặp phong cách A / B</FieldLabel>
            <div className="flex gap-2">
              <SelectBox
                id="bt-style-a"
                value={styleA}
                onChange={(e) => setStyleA(e.target.value)}
              >
                <option value="tiktok_karaoke">A: Karaoke</option>
                <option value="box_highlight">A: Hộp nổi</option>
                <option value="neon_glow">A: Neon</option>
              </SelectBox>
              <SelectBox
                aria-label="Phong cách biến thể B"
                value={styleB}
                onChange={(e) => setStyleB(e.target.value)}
              >
                <option value="box_highlight">B: Hộp nổi</option>
                <option value="neon_glow">B: Neon</option>
                <option value="minimal_bottom">B: Tối giản</option>
              </SelectBox>
            </div>
          </div>
        </div>

        {sourceKind === "products" ? (
          <div className="space-y-1.5">
            <span className="block text-[12.5px] font-medium text-[var(--text-secondary)]">
              Chọn sản phẩm đưa vào lô ({selectedProdIds.length} đã chọn)
            </span>
            <div className="flex flex-wrap gap-2">
              {products.map((p) => {
                const checked = selectedProdIds.includes(p.id);
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() =>
                      setSelectedProdIds((prev) =>
                        checked
                          ? prev.filter((x) => x !== p.id)
                          : [...prev, p.id]
                      )
                    }
                    className={`rounded-[9px] border px-3 py-1.5 text-[13px] font-medium cursor-pointer transition-colors ${
                      checked
                        ? "border-[var(--c-bd)] bg-[var(--c-soft)] text-[var(--c-tx)] font-semibold"
                        : "border-[var(--border-subtle)] bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:border-[var(--c-bd)]"
                    }`}
                  >
                    {p.name} ({p.material || "—"})
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          <div>
            <FieldLabel htmlFor="bt-prompts">
              {sourceKind === "prompts"
                ? "Danh sách ý tưởng (mỗi dòng 1 ý tưởng)"
                : "Danh sách mã Xu hướng (mỗi dòng 1 số ID)"}
            </FieldLabel>
            <TextareaBox
              id="bt-prompts"
              rows={3}
              value={promptsText}
              onChange={(e) => setPromptsText(e.target.value)}
            />
          </div>
        )}

        <Button type="submit">
          <Play className="w-4 h-4" /> Chạy Lô &amp; Sinh Biến Thể
        </Button>
      </form>
    </Card>
  );
}
