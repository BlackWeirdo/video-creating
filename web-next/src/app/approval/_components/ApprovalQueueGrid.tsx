"use client";

import React from "react";
import { AlertTriangle, Check, CheckCircle2, Download, X } from "lucide-react";
import type { ApprovalVideo } from "@/app/approval/types";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function ApprovalQueueGrid({
  pending,
  selectedIds,
  onToggleSelect,
  onToggleSelectAll,
  onApprove,
  onReject,
}: {
  pending: ApprovalVideo[];
  selectedIds: number[];
  onToggleSelect: (id: number) => void;
  onToggleSelectAll: () => void;
  onApprove: (id: number) => Promise<void>;
  onReject: (id: number) => Promise<void>;
}) {
  return (
    <Card tinted className="space-y-4">
      <CardTitleRow>
        <SectionHeading className="tabular-nums">
          Video Chờ Duyệt ({pending.length})
        </SectionHeading>
        {pending.length > 0 && (
          <button
            type="button"
            onClick={onToggleSelectAll}
            className="text-[12.5px] font-semibold text-[var(--c-tx)] hover:underline cursor-pointer"
          >
            {selectedIds.length === pending.length
              ? "Bỏ chọn tất cả"
              : "Chọn tất cả"}
          </button>
        )}
      </CardTitleRow>

      {pending.length === 0 ? (
        <EmptyState
          icon={<CheckCircle2 className="w-5 h-5" />}
          title="Không có video chờ duyệt"
          description="Tất cả video hoàn tất trong Workspace này đã được kiểm duyệt."
        />
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {pending.map((v) => (
            <article
              key={v.id}
              className="rounded-[12px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-4 space-y-3"
            >
              <div className="flex items-start justify-between gap-2">
                <label className="flex items-center gap-2.5 font-semibold text-[14px] text-[var(--text-primary)] cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(v.id)}
                    onChange={() => onToggleSelect(v.id)}
                    className="h-4 w-4 accent-[var(--c-solid)]"
                  />
                  <span>
                    #{v.id} — {v.plan?.title || "Chưa đặt tiêu đề"}
                  </span>
                </label>
                <Badge tone="neutral">
                  {v.aspect_ratio} • {v.style_preset}
                </Badge>
              </div>

              {v.output_url && (
                <div className="aspect-video w-full overflow-hidden rounded-[9px] bg-black border border-[var(--border-subtle)]">
                  <video
                    controls
                    src={v.output_url}
                    className="h-full w-full object-contain"
                  />
                </div>
              )}

              {v.unsupported_claims?.length > 0 && (
                <div className="flex items-start gap-2 rounded-[9px] border border-[var(--st-amber-bd)] bg-[var(--st-amber-bg)] px-3 py-2 text-[12.5px] text-[var(--st-amber-tx)]">
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>
                    Cảnh báo tuyên bố chưa đối chiếu dữ kiện:{" "}
                    {v.unsupported_claims.join(", ")}
                  </span>
                </div>
              )}

              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void onApprove(v.id)}
                >
                  <Check className="w-3.5 h-3.5" /> Duyệt đăng
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="danger"
                  onClick={() => void onReject(v.id)}
                >
                  <X className="w-3.5 h-3.5" /> Từ chối
                </Button>
                {v.output_url && (
                  <Button asChild size="sm" variant="secondary">
                    <a href={`/api/v1/videos/${v.id}/publish-pack`}>
                      <Download className="w-3.5 h-3.5" /> Gói 5 MXH (.zip)
                    </a>
                  </Button>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </Card>
  );
}
