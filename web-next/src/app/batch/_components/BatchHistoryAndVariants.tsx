"use client";

import React from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import type { BatchRunRow } from "@/app/batch/types";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function BatchHistoryAndVariants({
  batches,
  activeBatch,
  onSelectBatch,
  onRetryFailed,
}: {
  batches: BatchRunRow[];
  activeBatch: BatchRunRow | null;
  onSelectBatch: (id: number) => Promise<void>;
  onRetryFailed: (id: number) => Promise<void>;
}) {
  return (
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
                  onClick={() => void onSelectBatch(b.id)}
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
              onClick={() => void onRetryFailed(activeBatch.id)}
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
  );
}
