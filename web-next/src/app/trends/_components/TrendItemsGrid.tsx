"use client";

import React from "react";
import { ExternalLink, Flame, Languages, Layers, Play } from "lucide-react";
import type { TrendItem } from "@/app/trends/types";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function TrendItemsGrid({
  trends,
  onAnalyse,
  onSendToLocalize,
  onSendToBatch,
}: {
  trends: TrendItem[];
  onAnalyse: (id: number) => Promise<void>;
  onSendToLocalize: (id: number) => Promise<void>;
  onSendToBatch: (id: number) => Promise<void>;
}) {
  return (
    <Card className="space-y-3.5">
      <CardTitleRow>
        <SectionHeading className="tabular-nums">
          Danh sách Video Xu hướng ({trends.length})
        </SectionHeading>
      </CardTitleRow>

      {trends.length === 0 ? (
        <EmptyState
          icon={<Flame className="w-5 h-5" />}
          title="Chưa thu thập được video xu hướng nào"
          description="Thêm từ khóa theo dõi rồi bấm Quét Xu hướng Ngay ở góc phải trên."
        />
      ) : (
        <div className="grid md:grid-cols-2 gap-3.5">
          {trends.map((t) => (
            <article
              key={t.id}
              className="rounded-[12px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5 space-y-2.5"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <Badge tone="sky" className="uppercase mr-2 text-[11px]">
                    {t.source}
                  </Badge>
                  <span className="font-semibold text-[13.5px] text-[var(--text-primary)]">
                    {t.title || t.url}
                  </span>
                </div>
                <Badge tone="amber" className="tabular-nums">
                  Điểm: {t.score.toFixed(1)}
                </Badge>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-[var(--text-muted)]">
                <span>Phân tích: {t.analysis_status}</span>
                <div className="flex flex-wrap items-center gap-1.5">
                  {t.url && (
                    <Button asChild size="sm" variant="ghost">
                      <a href={t.url} target="_blank" rel="noreferrer">
                        <ExternalLink className="w-3.5 h-3.5" /> Mở gốc
                      </a>
                    </Button>
                  )}
                  <Button
                    type="button"
                    size="sm"
                    variant="emerald"
                    onClick={() => void onAnalyse(t.id)}
                  >
                    <Play className="w-3.5 h-3.5" /> Phân tích
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => void onSendToLocalize(t.id)}
                  >
                    <Languages className="w-3.5 h-3.5" /> Việt hóa
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="amber"
                    onClick={() => void onSendToBatch(t.id)}
                  >
                    <Layers className="w-3.5 h-3.5" /> Tạo A/B
                  </Button>
                </div>
              </div>

              {t.analysis && (
                <pre className="rounded-[8px] border border-[var(--border-subtle)] bg-[var(--bg-input)] p-2.5 font-mono text-[11.5px] text-[var(--text-secondary)] max-h-28 overflow-auto">
                  {JSON.stringify(t.analysis, null, 2)}
                </pre>
              )}
            </article>
          ))}
        </div>
      )}
    </Card>
  );
}
