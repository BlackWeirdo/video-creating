"use client";

import React from "react";
import { BookOpen, Play, RefreshCw } from "lucide-react";
import type { NovelProject } from "@/app/novel/types";
import { SimulationBadge } from "@/components/SimulationBadge";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, CardTitleRow } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function NovelProjectsList({
  projects,
  jobRunning,
  renderingId,
  onRender,
}: {
  projects: NovelProject[];
  jobRunning: boolean;
  renderingId: number | null;
  onRender: (projectId: number, force: boolean) => Promise<void>;
}) {
  if (projects.length === 0) {
    return (
      <EmptyState
        icon={<BookOpen className="w-5 h-5" />}
        title="Chưa có bộ truyện nào"
        description="Dán nội dung truyện vào biểu mẫu trên để tách chương và xuất video."
      />
    );
  }

  return (
    <div className="space-y-4">
      {projects.map((p) => (
        <Card key={p.id} className="space-y-3.5">
          <CardTitleRow>
            <div>
              <h2 className="text-[15.5px] font-bold text-[var(--text-primary)]">
                #{p.id} — {p.title}
              </h2>
              <div className="text-[12.5px] text-[var(--text-muted)] tabular-nums">
                {p.ready_chapters}/{p.total_chapters} chương hoàn tất •{" "}
                {p.aspect_ratio} •{" "}
                <strong className="text-[var(--c-tx)]">{p.status}</strong>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                disabled={jobRunning && renderingId === p.id}
                onClick={() => void onRender(p.id, false)}
              >
                <Play className="w-3.5 h-3.5" />{" "}
                {jobRunning && renderingId === p.id
                  ? "Đang xuất..."
                  : "Xuất tiếp chương còn thiếu"}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={jobRunning && renderingId === p.id}
                onClick={() => void onRender(p.id, true)}
              >
                <RefreshCw className="w-3.5 h-3.5" /> Xuất lại tất cả
              </Button>
            </div>
          </CardTitleRow>

          <SimulationBadge flags={p.simulation_flags} />

          <div className="grid md:grid-cols-2 gap-3">
            {p.chapters.map((ch) => (
              <div
                key={ch.id}
                className="rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5 space-y-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[13.5px] font-semibold text-[var(--text-primary)]">
                    {ch.title}
                  </span>
                  <Badge tone={ch.status === "ready" ? "emerald" : "neutral"}>
                    {ch.status}
                  </Badge>
                </div>
                {ch.video_url && (
                  <video
                    controls
                    preload="metadata"
                    src={ch.video_url}
                    className="w-full max-h-48 rounded-[8px] bg-black"
                  />
                )}
              </div>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
}
