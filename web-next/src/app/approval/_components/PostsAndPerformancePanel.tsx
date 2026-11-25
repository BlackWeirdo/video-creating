"use client";

import React from "react";
import { RefreshCw } from "lucide-react";
import type { PerfItem, PostItem } from "@/app/approval/types";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, SectionHeading } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export function PostsAndPerformancePanel({
  posts,
  perf,
  onRetryPost,
}: {
  posts: PostItem[];
  perf: PerfItem[];
  onRetryPost: (postId: number) => Promise<void>;
}) {
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <Card className="space-y-3">
        <SectionHeading className="tabular-nums">
          Lịch đăng ({posts.length})
        </SectionHeading>
        {posts.length === 0 ? (
          <EmptyState title="Chưa có bài đăng nào trong lịch" />
        ) : (
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {posts.map((p) => (
              <div
                key={p.id}
                className="flex items-center justify-between gap-2 rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3.5 py-2.5"
              >
                <div>
                  <div className="text-[13.5px] font-semibold text-[var(--text-primary)]">
                    Video #{p.video_id} → {p.platform} ({p.account_name})
                  </div>
                  <div className="text-[12px] text-[var(--text-muted)] tabular-nums">
                    {p.status} • {p.scheduled_at}
                  </div>
                </div>
                {["failed", "missed"].includes(p.status) && (
                  <Button
                    type="button"
                    size="sm"
                    variant="amber"
                    onClick={() => void onRetryPost(p.id)}
                  >
                    <RefreshCw className="w-3.5 h-3.5" /> Thử lại
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="space-y-3">
        <SectionHeading className="tabular-nums">
          Hiệu quả sau 24 giờ / 72 giờ / 7 ngày ({perf.length})
        </SectionHeading>
        {perf.length === 0 ? (
          <EmptyState title="Chưa có số liệu hiệu quả bài đăng" />
        ) : (
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {perf.map((item) => (
              <div
                key={item.post_id}
                className="rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3.5 py-2.5 space-y-1"
              >
                <div className="text-[13.5px] font-semibold text-[var(--text-primary)]">
                  {item.title} ({item.platform})
                </div>
                <div className="text-[12px] text-[var(--text-muted)] tabular-nums">
                  24h: {item.checkpoints?.["24h"]?.views ?? "—"} lượt xem • 72h:{" "}
                  {item.checkpoints?.["72h"]?.views ?? "—"} lượt xem • 7d:{" "}
                  {item.checkpoints?.["7d"]?.views ?? "—"} lượt xem
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
