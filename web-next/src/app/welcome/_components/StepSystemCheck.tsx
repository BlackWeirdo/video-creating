"use client";

import React from "react";
import type { OnboardingStatus } from "@/app/welcome/types";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function StepSystemCheck({
  status,
  onNext,
}: {
  status: OnboardingStatus;
  onNext: () => void;
}) {
  const checks = [
    {
      name: "Bộ kết xuất video FFmpeg",
      ok: status.runtime.ffmpeg_ready,
      note: status.runtime.ffmpeg_path,
    },
    {
      name: "Bộ đo kiểm âm lượng FFprobe",
      ok: status.runtime.ffprobe_ready,
      note: "Đo thời lượng & chuẩn -14 LUFS",
    },
    {
      name: "Môi trường giao diện Node 24 LTS",
      ok: status.runtime.node_ready,
      note: status.runtime.node_path || "Next.js 15 & Remotion",
    },
    {
      name: "Trình tải nguồn tham khảo yt-dlp",
      ok: status.runtime.ytdlp_ready,
      note: "Hỗ trợ xu hướng & nguồn Việt hóa",
    },
  ];

  return (
    <Card tinted className="space-y-4">
      <SectionHeading>
        Kiểm tra Công cụ Đóng Gói Cục Bộ trên Máy Trạm
      </SectionHeading>
      <div className="grid md:grid-cols-2 gap-3">
        {checks.map((chk) => (
          <div
            key={chk.name}
            className="flex items-center justify-between gap-2 rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5"
          >
            <div className="min-w-0">
              <div className="text-[13.5px] font-bold text-[var(--text-primary)]">
                {chk.name}
              </div>
              <div className="truncate text-[12px] text-[var(--text-muted)]">
                {chk.note}
              </div>
            </div>
            <Badge tone={chk.ok ? "emerald" : "amber"}>
              {chk.ok ? "Sẵn sàng" : "Thiếu"}
            </Badge>
          </div>
        ))}
      </div>
      <div className="flex justify-end">
        <Button type="button" onClick={onNext}>
          Tiếp tục: Thương hiệu →
        </Button>
      </div>
    </Card>
  );
}
