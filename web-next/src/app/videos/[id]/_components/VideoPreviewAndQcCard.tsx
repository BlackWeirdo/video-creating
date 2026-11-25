"use client";

import React from "react";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export interface VideoQcInfo {
  passed?: boolean;
  integrated_lufs?: number | null;
  issues?: string[];
}

export function VideoPreviewAndQcCard({
  outputUrl,
  qc,
}: {
  outputUrl: string | null;
  qc: VideoQcInfo;
}) {
  return (
    <Card className="lg:col-span-2 space-y-4">
      <SectionHeading>Xem trước Thành phẩm &amp; Kiểm định Kỹ thuật</SectionHeading>
      {outputUrl ? (
        <video
          controls
          src={outputUrl}
          className="w-full max-h-96 rounded-[10px] bg-black border border-[var(--border-subtle)]"
        />
      ) : (
        <EmptyState
          title="Chưa có tệp MP4 thành phẩm"
          description='Bấm nút "Dựng Video" ở góc phải trên để xuất tệp MP4.'
        />
      )}

      <div className="rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5 space-y-1.5 text-[13px]">
        <div className="font-bold text-[var(--text-primary)]">
          Báo cáo Kiểm định Âm lượng &amp; Khung hình (QC)
        </div>
        {qc?.passed === undefined ? (
          <div className="text-[var(--text-muted)]">
            Chưa chạy kiểm định kỹ thuật.
          </div>
        ) : (
          <>
            <Badge tone={qc.passed ? "emerald" : "rose"}>
              {qc.passed
                ? "✓ Đạt toàn bộ chỉ tiêu kỹ thuật"
                : "✗ Phát hiện lỗi kỹ thuật"}
            </Badge>
            {qc.integrated_lufs !== undefined && qc.integrated_lufs !== null && (
              <div className="text-[12.5px] text-[var(--text-secondary)] tabular-nums pt-1">
                Độ lớn âm thanh trung bình:{" "}
                <strong>{qc.integrated_lufs.toFixed(1)} LUFS</strong>
              </div>
            )}
            {qc.issues?.map((issue, i) => (
              <div key={i} className="text-[12.5px] text-[var(--st-rose-tx)]">
                • {issue}
              </div>
            ))}
          </>
        )}
      </div>
    </Card>
  );
}
