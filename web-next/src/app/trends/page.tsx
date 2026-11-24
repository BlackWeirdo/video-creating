"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Flame, Link2, Play, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";

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
        apiFetch<{ watchlist: WatchItem[] }>(`/api/v1/watchlist?workspace_id=${activeWorkspaceId}`),
        apiFetch<{ trends: TrendItem[] }>(`/api/v1/trends?workspace_id=${activeWorkspaceId}`),
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
      await loadAll();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể thêm watchlist");
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
    setMsg(`Đã xếp hàng đợi quét xu hướng (Job #${res.job_id}).`);
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
      setMsg("Đã nạp link tham khảo & xếp hàng đợi phân tích rea-video.");
      await loadAll();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không đọc được link");
    }
  };

  const analyseItem = async (id: number) => {
    await apiFetch(`/api/v1/trends/${id}/analyse`, { method: "POST" });
    setMsg(`Đã đưa Trend #${id} vào hàng đợi phân tích.`);
    await loadAll();
  };

  const handleSuggestion = async (id: number, action: "accept" | "dismiss") => {
    await apiFetch(`/api/v1/suggestions/${id}/${action}`, {
      method: "POST",
      body: action === "accept" ? JSON.stringify({ workspace_id: activeWorkspaceId }) : undefined,
    });
    setMsg(action === "accept" ? `Đã nhận đề xuất #${id} và tạo kịch bản.` : `Đã bỏ qua đề xuất #${id}.`);
    await loadAll();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Flame className="w-6 h-6 text-amber-400" /> Xu hướng & Phân tích Công thức
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Quét 5 nguồn xu hướng, dán link Reels/TikTok tham khảo, phân tích `rea-video` và tạo đề xuất.
          </p>
        </div>
        <button
          onClick={() => void triggerScan()}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-xs cursor-pointer"
        >
          <RefreshCw className="w-4 h-4" /> Quét Xu hướng Ngay
        </button>
      </div>

      {msg && (
        <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs rounded-lg px-4 py-2.5">
          {msg}
        </div>
      )}
      {err && (
        <div className="bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs rounded-lg px-4 py-2.5">
          {err}
        </div>
      )}

      {/* Watchlist & Paste Link */}
      <div className="grid md:grid-cols-2 gap-4">
        <form
          onSubmit={addWatch}
          className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3"
        >
          <h2 className="text-sm font-semibold text-white">Theo dõi Kênh / Từ khóa</h2>
          <div className="grid grid-cols-2 gap-2">
            <select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="bg-[#182235] border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
            >
              <option value="youtube">YouTube Shorts</option>
              <option value="tiktok">TikTok (Apify)</option>
              <option value="ig_hashtag">Instagram Hashtag</option>
              <option value="ig_discovery">Instagram Discovery</option>
              <option value="facebook">Facebook Reels Page</option>
              <option value="ad_library">Meta Ad Library</option>
            </select>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              className="bg-[#182235] border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
            >
              <option value="keyword">Keyword</option>
              <option value="hashtag">Hashtag</option>
              <option value="account">Account</option>
              <option value="page">Page</option>
            </select>
          </div>
          <div className="flex gap-2">
            <input
              required
              value={watchVal}
              onChange={(e) => setWatchVal(e.target.value)}
              placeholder="Nhập từ khóa hoặc link page..."
              className="flex-1 bg-[#182235] border border-slate-700 rounded-lg px-3 py-2 text-xs"
            />
            <button
              type="submit"
              className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-sky-300 border border-slate-700 text-xs font-medium cursor-pointer"
            >
              Thêm
            </button>
          </div>
          <div className="space-y-1.5 max-h-40 overflow-y-auto pt-1">
            {watchlist.map((w) => (
              <div
                key={w.id}
                className="flex items-center justify-between text-xs bg-[#182235]/60 rounded px-2.5 py-1.5"
              >
                <span>
                  <strong className="text-sky-300">{w.source}</strong>/{w.kind}: {w.value}
                </span>
                <button
                  type="button"
                  onClick={() => void deleteWatch(w.id)}
                  className="text-slate-400 hover:text-rose-400 cursor-pointer"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </form>

        <form
          onSubmit={submitLink}
          className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3"
        >
          <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
            <Link2 className="w-4 h-4 text-sky-400" /> Dán Link Video Tham Khảo
          </h2>
          <p className="text-xs text-slate-400">
            Dán link Facebook Reel hoặc Instagram Reel công khai để ghim phân tích cấu trúc `rea-video`.
          </p>
          <div className="flex gap-2">
            <input
              required
              value={pasteUrl}
              onChange={(e) => setPasteUrl(e.target.value)}
              placeholder="https://www.facebook.com/reel/..."
              className="flex-1 bg-[#182235] border border-slate-700 rounded-lg px-3 py-2 text-xs"
            />
            <button
              type="submit"
              className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 text-xs font-semibold cursor-pointer"
            >
              Nạp Link
            </button>
          </div>

          <div className="pt-2 space-y-2">
            <h3 className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-purple-400" /> Đề xuất Ý tưởng ({suggestions.length})
            </h3>
            <div className="space-y-2 max-h-40 overflow-y-auto">
              {suggestions.map((s) => (
                <div
                  key={s.id}
                  className="bg-[#182235] border border-slate-700/70 rounded-lg p-2.5 text-xs space-y-1.5"
                >
                  <div className="text-slate-200">{s.text}</div>
                  <div className="flex items-center justify-between text-[11px] text-slate-400">
                    <span>Trạng thái: {s.status}</span>
                    {["new", "sent"].includes(s.status) && (
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => void handleSuggestion(s.id, "accept")}
                          className="text-emerald-300 hover:underline cursor-pointer"
                        >
                          Nhận đề xuất
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleSuggestion(s.id, "dismiss")}
                          className="text-slate-400 hover:text-rose-300 cursor-pointer"
                        >
                          Bỏ qua
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </form>
      </div>

      {/* Trends List */}
      <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3">
        <h2 className="text-sm font-semibold text-white">
          Danh sách Video Xu hướng ({trends.length})
        </h2>
        {trends.length === 0 ? (
          <div className="text-xs text-slate-500 py-4">Chưa có video xu hướng nào trong Workspace này.</div>
        ) : (
          <div className="grid md:grid-cols-2 gap-3">
            {trends.map((t) => (
              <div
                key={t.id}
                className="bg-[#182235] border border-slate-700/70 rounded-lg p-3 space-y-2 text-xs"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-slate-800 text-sky-300 mr-1.5">
                      {t.source}
                    </span>
                    <span className="font-medium text-white">{t.title || t.url}</span>
                  </div>
                  <span className="text-amber-300 font-semibold shrink-0">
                    {t.score.toFixed(1)}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[11px] text-slate-400">
                  <span>Phân tích: {t.analysis_status}</span>
                  <div className="flex gap-3">
                    {t.url && (
                      <a
                        href={t.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-sky-400 hover:underline"
                      >
                        Mở nguồn
                      </a>
                    )}
                    <button
                      type="button"
                      onClick={() => void analyseItem(t.id)}
                      className="inline-flex items-center gap-1 text-emerald-300 hover:underline cursor-pointer"
                    >
                      <Play className="w-3 h-3" /> Phân tích
                    </button>
                  </div>
                </div>
                {t.analysis && (
                  <pre className="bg-[#0b0f17] rounded p-2 text-[10px] text-slate-300 max-h-28 overflow-auto">
                    {JSON.stringify(t.analysis, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
