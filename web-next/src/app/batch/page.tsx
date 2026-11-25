"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Layers, Play, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { JobProgressBanner, useJobProgress } from "@/components/JobProgressBanner";
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

interface ProductOption {
  id: number;
  name: string;
  material: string;
}

interface BatchItemRow {
  id: number;
  item_index: number;
  variant_label: string;
  style_preset: string;
  hook_angle: string;
  step: string;
  video_id: number | null;
  video_status: string | null;
  video_quality_score: number | null;
  error: string | null;
}

interface BatchRunRow {
  id: number;
  title: string;
  source_kind: string;
  ab_count: number;
  status: string;
  total_items?: number;
  completed_items?: number;
  failed_items?: number;
  items?: BatchItemRow[];
}

export default function BatchStudioPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [batches, setBatches] = useState<BatchRunRow[]>([]);
  const [activeBatch, setActiveBatch] = useState<BatchRunRow | null>(null);
  const [products, setProducts] = useState<ProductOption[]>([]);

  const [title, setTitle] = useState("");
  const [sourceKind, setSourceKind] = useState<
    "products" | "prompts" | "trends"
  >("products");
  const [selectedProdIds, setSelectedProdIds] = useState<number[]>([]);
  const [promptsText, setPromptsText] = useState("");
  const [abCount, setAbCount] = useState(2);
  const [styleA, setStyleA] = useState("tiktok_karaoke");
  const [styleB, setStyleB] = useState("box_highlight");
  const [activeJobId, setActiveJobId] = useState<number | null>(null);

  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [bRes, pRes] = await Promise.all([
        apiFetch<{ batches: BatchRunRow[] }>(
          `/api/v1/batches?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ products: ProductOption[] }>(
          `/api/v1/products?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      const list = bRes.batches || [];
      setBatches(list);
      setProducts(pRes.products || []);
      if (list.length > 0) {
        const detail = await apiFetch<{ batch: BatchRunRow }>(
          `/api/v1/batches/${list[0].id}`
        );
        setActiveBatch(detail.batch);
      }
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Sản xuất hàng loạt");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const { job: activeJob } = useJobProgress(activeJobId, {
    onStepChange: () => {
      void load();
    },
    onCompleted: () => {
      setMsg("Đã hoàn tất chạy lô sản xuất hàng loạt (A/B)!");
      toast.success("Hoàn tất lô sản xuất hàng loạt!");
      void load();
    },
    onFailed: (j) => {
      setErr(j.error || "Lô sản xuất gặp lỗi");
      void load();
    },
  });

  const inspectBatch = async (id: number) => {
    const detail = await apiFetch<{ batch: BatchRunRow }>(`/api/v1/batches/${id}`);
    setActiveBatch(detail.batch);
  };

  const createBatch = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
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
            workspace_id: activeWorkspaceId,
            title: title || `Chiến dịch ${sourceKind}`,
            source_kind: sourceKind,
            items,
            ab_count: abCount,
            style_presets: [styleA, styleB],
            sync: false,
          }),
        }
      );
      setTitle("");
      setPromptsText("");
      setActiveJobId(res.job_id);
      const m = `Đã khởi chạy lô #${res.batch.id} (Tác vụ #${res.job_id}).`;
      setMsg(m);
      toast.info(m);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo lô sản xuất");
    }
  };

  const retryFailed = async (id: number) => {
    const res = await apiFetch<{ job_id: number }>(`/api/v1/batches/${id}/retry`, {
      method: "POST",
      body: JSON.stringify({ failed_only: true, sync: false }),
    });
    setActiveJobId(res.job_id);
    const m = `Đã chạy lại các mục lỗi từ điểm lưu của lô #${id} (Tác vụ #${res.job_id}).`;
    setMsg(m);
    toast.info(m);
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        icon={<Layers className="w-5 h-5" />}
        title="Sản Xuất Hàng Loạt & Biến Thể A/B"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {batches.length} chiến dịch
          </Badge>
        }
        description="Tự động nhân bản 1–3 biến thể góc mở đầu (Hook) và kiểu phụ đề A/B/C cho nhiều sản phẩm cùng lúc, hỗ trợ chạy lại đúng bước bị lỗi."
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
        label="Sản xuất hàng loạt"
        onDismiss={() => setActiveJobId(null)}
      />

      <Card tinted>
        <form onSubmit={createBatch} className="space-y-4">
          <SectionHeading>Khởi Chạy Chiến Dịch Hàng Loạt Mới</SectionHeading>

          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-3.5">
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

      <div className="grid lg:grid-cols-3 gap-4 items-start">
        <Card className="space-y-3">
          <SectionHeading className="tabular-nums">
            Lịch sử Chiến dịch ({batches.length})
          </SectionHeading>
          {batches.length === 0 ? (
            <EmptyState title="Chưa có lô sản xuất nào" />
          ) : (
            <div className="space-y-2">
              {batches.map((b) => {
                const isSelected = activeBatch?.id === b.id;
                return (
                  <div
                    key={b.id}
                    onClick={() => void inspectBatch(b.id)}
                    className={`rounded-[11px] border p-3 cursor-pointer space-y-1 transition-colors ${
                      isSelected
                        ? "border-[var(--c-bd)] bg-[var(--c-soft)]"
                        : "border-[var(--border-subtle)] bg-[var(--bg-elevated)] hover:border-[var(--c-bd)]"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <strong className="text-[13.5px] text-[var(--text-primary)]">
                        {b.title}
                      </strong>
                      <Badge tone="sky">{b.status}</Badge>
                    </div>
                    <div className="text-[12px] text-[var(--text-muted)] tabular-nums">
                      {b.source_kind} • {b.completed_items ?? 0}/
                      {b.total_items ?? 0} xong
                      {b.failed_items ? ` • ${b.failed_items} lỗi` : ""}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        <Card className="lg:col-span-2 space-y-3.5">
          <CardTitleRow>
            <SectionHeading>
              Biến thể A/B &amp; Trạng thái từng bước
              {activeBatch ? ` — #${activeBatch.id}` : ""}
            </SectionHeading>
            {activeBatch && (
              <Button
                type="button"
                size="sm"
                variant="amber"
                onClick={() => void retryFailed(activeBatch.id)}
              >
                <RefreshCw className="w-3.5 h-3.5" /> Thử lại mục lỗi
              </Button>
            )}
          </CardTitleRow>

          {!activeBatch?.items?.length ? (
            <EmptyState title="Chọn một chiến dịch để xem danh sách biến thể" />
          ) : (
            <div className="grid md:grid-cols-2 gap-3">
              {activeBatch.items.map((it) => (
                <div
                  key={it.id}
                  className="rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5 space-y-1.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <strong className="text-[13.5px] text-[var(--text-primary)] tabular-nums">
                      Mục #{it.item_index + 1} • Bản {it.variant_label}
                    </strong>
                    <Badge tone={it.error ? "rose" : "emerald"}>{it.step}</Badge>
                  </div>
                  <div className="text-[12px] text-[var(--text-muted)]">
                    Phong cách: {it.style_preset} • Mở đầu: {it.hook_angle}
                  </div>
                  {it.video_quality_score !== null && (
                    <div className="text-[12px] font-semibold text-[var(--st-amber-tx)] tabular-nums">
                      Điểm kiểm định: {it.video_quality_score.toFixed(1)}
                    </div>
                  )}
                  {it.error && (
                    <div className="text-[12px] text-[var(--st-rose-tx)]">
                      {it.error}
                    </div>
                  )}
                  {it.video_id && (
                    <Link
                      href={`/videos/${it.video_id}`}
                      className="inline-block pt-1 text-[12.5px] font-semibold text-[var(--c-tx)] hover:underline"
                    >
                      Mở Video #{it.video_id} →
                    </Link>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
