"use client";

import React, { useState } from "react";
import { Flame, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import type { SuggestionItem, TrendItem, WatchItem } from "@/app/trends/types";
import { WatchlistAndLinkPanel } from "@/app/trends/_components/WatchlistAndLinkPanel";
import { TrendItemsGrid } from "@/app/trends/_components/TrendItemsGrid";
import { PageHeader } from "@/components/vc/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface TrendsPageBundle {
  watchlist: WatchItem[];
  trends: TrendItem[];
  suggestions: SuggestionItem[];
}

export default function TrendsPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [msg, setMsg] = useState("");

  const { data, error: err, setError: setErr, reload: loadAll } =
    useApiQuery<TrendsPageBundle>(
      async (signal) => {
        const [wRes, tRes, sRes] = await Promise.all([
          apiFetch<{ watchlist: WatchItem[] }>(
            `/api/v1/watchlist?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
          apiFetch<{ trends: TrendItem[] }>(
            `/api/v1/trends?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
          apiFetch<{ suggestions: SuggestionItem[] }>(
            `/api/v1/suggestions?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
        ]);
        return {
          watchlist: wRes.watchlist || [],
          trends: tRes.trends || [],
          suggestions: sRes.suggestions || [],
        };
      },
      [activeWorkspaceId],
      { fallbackError: "Lỗi tải xu hướng" }
    );

  const watchlist = data?.watchlist || [];
  const trends = data?.trends || [];
  const suggestions = data?.suggestions || [];

  const triggerScan = async () => {
    const res = await apiFetch<{ job_id: number }>("/api/v1/trends/scan", {
      method: "POST",
      body: JSON.stringify({ workspace_id: activeWorkspaceId }),
    });
    const m = `Đã đưa vào hàng đợi quét xu hướng (Tác vụ #${res.job_id}).`;
    setMsg(m);
    toast.info(m);
  };

  const analyseItem = async (id: number) => {
    await apiFetch(`/api/v1/trends/${id}/analyse`, { method: "POST" });
    const m = `Đã đưa video xu hướng #${id} vào hàng đợi phân tích.`;
    setMsg(m);
    toast.info(m);
    await loadAll();
  };

  const sendTrendToLocalize = async (trendId: number) => {
    setErr("");
    try {
      const res = await apiFetch<{ project: { id: number } }>(
        `/api/v1/trends/${trendId}/send-to-localize`,
        { method: "POST", body: JSON.stringify({ workspace_id: activeWorkspaceId }) }
      );
      const m = `Đã chuyển video #${trendId} sang Studio Việt hóa (#${res.project.id}).`;
      setMsg(m);
      toast.success(m);
    } catch (e2) {
      setErr(
        e2 instanceof Error
          ? e2.message
          : "Chính sách Workspace hiện tại không cho phép Việt hóa video này"
      );
    }
  };

  const sendTrendToBatch = async (trendId: number) => {
    setErr("");
    try {
      const res = await apiFetch<{ batch: { id: number } }>(
        "/api/v1/trends/send-to-batch",
        {
          method: "POST",
          body: JSON.stringify({
            workspace_id: activeWorkspaceId,
            trend_ids: [trendId],
            ab_count: 2,
          }),
        }
      );
      const m = `Đã tạo lô thử nghiệm A/B #${res.batch.id} từ video #${trendId}.`;
      setMsg(m);
      toast.success(m);
    } catch (e2) {
      setErr(
        e2 instanceof Error
          ? e2.message
          : "Không thể chuyển sang Sản xuất hàng loạt"
      );
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        icon={<Flame className="w-5 h-5" />}
        title="Xu hướng & Phân tích Công thức Giữ Chân"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {trends.length} xu hướng • {suggestions.length} đề xuất
          </Badge>
        }
        description="Quét 5 nguồn xu hướng tự động, dán liên kết Reels / TikTok tham khảo để bóc tách cấu trúc mở đầu (Hook), nhịp cắt cảnh và sinh ý tưởng kịch bản."
        actions={
          <Button type="button" onClick={() => void triggerScan()}>
            <RefreshCw className="w-4 h-4" /> Quét Xu hướng Ngay
          </Button>
        }
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

      <WatchlistAndLinkPanel
        workspaceId={activeWorkspaceId}
        watchlist={watchlist}
        suggestions={suggestions}
        onReload={loadAll}
        onMessage={setMsg}
        onError={setErr}
      />

      <TrendItemsGrid
        trends={trends}
        onAnalyse={analyseItem}
        onSendToLocalize={sendTrendToLocalize}
        onSendToBatch={sendTrendToBatch}
      />
    </div>
  );
}
