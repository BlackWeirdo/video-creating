"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  ExternalLink,
  Flame,
  Languages,
  Layers,
  Link2,
  Play,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { PageHeader } from "@/components/vc/PageHeader";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextInput } from "@/components/ui/form-controls";

interface WatchItem {
  id: number;
  source: string;
  kind: string;
  value: string;
  enabled: number;
}

interface TrendItem {
  id: number;
  source: string;
  title: string;
  url: string;
  score: number;
  analysis_status: string;
  analysis: Record<string, unknown> | null;
}

interface SuggestionItem {
  id: number;
  text: string;
  status: string;
  formula: Record<string, unknown>;
}

export default function TrendsPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [watchlist, setWatchlist] = useState<WatchItem[]>([]);
  const [trends, setTrends] = useState<TrendItem[]>([]);
  const [suggestions, setSuggestions] = useState<SuggestionItem[]>([]);
  const [source, setSource] = useState("youtube");
  const [kind, setKind] = useState("keyword");
  const [watchVal, setWatchVal] = useState("");
  const [pasteUrl, setPasteUrl] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const loadAll = useCallback(async () => {
    try {
      const [wRes, tRes, sRes] = await Promise.all([
        apiFetch<{ watchlist: WatchItem[] }>(
          `/api/v1/watchlist?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ trends: TrendItem[] }>(
          `/api/v1/trends?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ suggestions: SuggestionItem[] }>(
          `/api/v1/suggestions?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      setWatchlist(wRes.watchlist || []);
      setTrends(tRes.trends || []);
      setSuggestions(sRes.suggestions || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải xu hướng");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const addWatch = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      await apiFetch("/api/v1/watchlist", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          source,
          kind,
          value: watchVal,
        }),
      });
      setWatchVal("");
      setMsg("Đã thêm từ khóa / kênh theo dõi.");
      toast.success("Đã thêm vào danh sách theo dõi.");
      await loadAll();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể thêm nguồn theo dõi");
    }
  };

  const deleteWatch = async (id: number) => {
    await apiFetch(`/api/v1/watchlist/${id}`, { method: "DELETE" });
    await loadAll();
  };

  const triggerScan = async () => {
    const res = await apiFetch<{ job_id: number }>("/api/v1/trends/scan", {
      method: "POST",
      body: JSON.stringify({ workspace_id: activeWorkspaceId }),
    });
    const m = `Đã đưa vào hàng đợi quét xu hướng (Tác vụ #${res.job_id}).`;
    setMsg(m);
    toast.info(m);
  };

  const submitLink = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      await apiFetch("/api/v1/trends/link", {
        method: "POST",
        body: JSON.stringify({ workspace_id: activeWorkspaceId, url: pasteUrl }),
      });
      setPasteUrl("");
      const m = "Đã nạp liên kết tham khảo & đưa vào hàng đợi phân tích cấu trúc.";
      setMsg(m);
      toast.success(m);
      await loadAll();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không đọc được liên kết");
    }
  };

  const analyseItem = async (id: number) => {
    await apiFetch(`/api/v1/trends/${id}/analyse`, { method: "POST" });
    const m = `Đã đưa video xu hướng #${id} vào hàng đợi phân tích.`;
    setMsg(m);
    toast.info(m);
    await loadAll();
  };

  const handleSuggestion = async (id: number, action: "accept" | "dismiss") => {
    await apiFetch(`/api/v1/suggestions/${id}/${action}`, {
      method: "POST",
      body:
        action === "accept"
          ? JSON.stringify({ workspace_id: activeWorkspaceId })
          : undefined,
    });
    const m =
      action === "accept"
        ? `Đã nhận đề xuất #${id} và khởi tạo kịch bản.`
        : `Đã bỏ qua đề xuất #${id}.`;
    setMsg(m);
    toast.success(m);
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

      <div className="grid lg:grid-cols-2 gap-4">
        <Card tinted>
          <form onSubmit={addWatch} className="space-y-3.5">
            <SectionHeading>Theo dõi Kênh / Từ khóa tự động</SectionHeading>
            <div className="grid sm:grid-cols-2 gap-3">
              <div>
                <FieldLabel htmlFor="tr-src">Nguồn nền tảng</FieldLabel>
                <SelectBox
                  id="tr-src"
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                >
                  <option value="youtube">YouTube Shorts</option>
                  <option value="tiktok">TikTok</option>
                  <option value="ig_hashtag">Instagram Hashtag</option>
                  <option value="ig_discovery">Instagram Khám phá</option>
                  <option value="facebook">Facebook Reels Page</option>
                  <option value="ad_library">Thư viện Quảng cáo Meta</option>
                </SelectBox>
              </div>
              <div>
                <FieldLabel htmlFor="tr-kind">Loại theo dõi</FieldLabel>
                <SelectBox
                  id="tr-kind"
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  <option value="keyword">Từ khóa</option>
                  <option value="hashtag">Thẻ Hashtag</option>
                  <option value="account">Tài khoản</option>
                  <option value="page">Trang Fanpage</option>
                </SelectBox>
              </div>
            </div>

            <div className="flex gap-2 items-end">
              <div className="flex-1">
                <FieldLabel htmlFor="tr-val">Từ khóa hoặc địa chỉ kênh *</FieldLabel>
                <TextInput
                  id="tr-val"
                  required
                  value={watchVal}
                  onChange={(e) => setWatchVal(e.target.value)}
                  placeholder="VD: dây chuyền bạc s925..."
                />
              </div>
              <Button type="submit" variant="secondary">
                <Plus className="w-4 h-4" /> Thêm
              </Button>
            </div>

            {watchlist.length > 0 && (
              <div className="space-y-1.5 max-h-44 overflow-y-auto pt-1">
                {watchlist.map((w) => (
                  <div
                    key={w.id}
                    className="flex items-center justify-between gap-2 rounded-[9px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px]"
                  >
                    <span className="truncate">
                      <Badge tone="cluster" className="mr-2 uppercase text-[11px]">
                        {w.source}
                      </Badge>
                      <span className="text-[var(--text-muted)]">{w.kind}: </span>
                      <strong className="text-[var(--text-primary)]">{w.value}</strong>
                    </span>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      aria-label={`Xóa theo dõi ${w.value}`}
                      onClick={() => void deleteWatch(w.id)}
                    >
                      <Trash2 className="w-4 h-4 text-rose-400" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </form>
        </Card>

        <Card className="space-y-4">
          <form onSubmit={submitLink} className="space-y-3">
            <SectionHeading>
              <Link2 className="w-4 h-4 text-[var(--c-icon)]" /> Dán Liên Kết Video Tham Khảo
            </SectionHeading>
            <p className="text-[12.5px] text-[var(--text-muted)]">
              Dán liên kết Reels hoặc Shorts công khai để hệ thống tự bóc tách cấu trúc giữ chân người xem.
            </p>
            <div className="flex gap-2 items-end">
              <div className="flex-1">
                <FieldLabel htmlFor="tr-url">Liên kết video công khai *</FieldLabel>
                <TextInput
                  id="tr-url"
                  required
                  value={pasteUrl}
                  onChange={(e) => setPasteUrl(e.target.value)}
                  placeholder="https://www.facebook.com/reel/..."
                />
              </div>
              <Button type="submit">Nạp Liên Kết</Button>
            </div>
          </form>

          <div className="border-t border-[var(--border-subtle)] pt-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 text-[13.5px] font-bold text-[var(--text-primary)]">
                <Sparkles className="w-4 h-4 text-[var(--c-icon)]" /> Đề xuất Ý tưởng ({suggestions.length})
              </span>
            </div>

            {suggestions.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                Chưa có đề xuất kịch bản mới.
              </p>
            ) : (
              <div className="space-y-2 max-h-44 overflow-y-auto">
                {suggestions.map((s) => (
                  <div
                    key={s.id}
                    className="rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 space-y-2 text-[13px]"
                  >
                    <div className="text-[var(--text-primary)]">{s.text}</div>
                    <div className="flex items-center justify-between gap-2">
                      <Badge tone="neutral">{s.status}</Badge>
                      {["new", "sent"].includes(s.status) && (
                        <div className="flex gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="emerald"
                            onClick={() => void handleSuggestion(s.id, "accept")}
                          >
                            Nhận ý tưởng
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => void handleSuggestion(s.id, "dismiss")}
                          >
                            Bỏ qua
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      </div>

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
                      onClick={() => void analyseItem(t.id)}
                    >
                      <Play className="w-3.5 h-3.5" /> Phân tích
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={() => void sendTrendToLocalize(t.id)}
                    >
                      <Languages className="w-3.5 h-3.5" /> Việt hóa
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="amber"
                      onClick={() => void sendTrendToBatch(t.id)}
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
    </div>
  );
}
