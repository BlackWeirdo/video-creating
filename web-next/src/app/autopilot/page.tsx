"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Bot, Play, Trash2 } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";

interface AutopilotRule {
  id: number;
  name: string;
  enabled: boolean;
  source_mode: "suggestions" | "products_ab" | "rss_feed" | "localize_trends";
  feed_url: string;
  daily_cap: number;
  min_quality_score: number;
  style_preset: string;
  interval_minutes: number;
  last_status: string;
  last_error: string | null;
  total_generated: number;
}

interface AutopilotRun {
  id: number;
  rule_id: number;
  source_summary: string;
  video_id: number | null;
  status: string;
  detail: string;
  created_at: string;
}

export default function AutopilotPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [rules, setRules] = useState<AutopilotRule[]>([]);
  const [runs, setRuns] = useState<AutopilotRun[]>([]);

  const [name, setName] = useState("");
  const [sourceMode, setSourceMode] = useState<"suggestions" | "products_ab" | "rss_feed" | "localize_trends">("products_ab");
  const [feedUrl, setFeedUrl] = useState("");
  const [dailyCap, setDailyCap] = useState(3);
  const [minScore, setMinScore] = useState(8.0);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [rRes, runRes] = await Promise.all([
        apiFetch<{ rules: AutopilotRule[] }>(
          `/api/v1/autopilot/rules?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ runs: AutopilotRun[] }>(
          `/api/v1/autopilot/runs?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      setRules(rRes.rules || []);
      setRuns(runRes.runs || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Autopilot");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const createRule = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      await apiFetch("/api/v1/autopilot/rules", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          name,
          source_mode: sourceMode,
          feed_url: feedUrl,
          daily_cap: dailyCap,
          min_quality_score: minScore,
        }),
      });
      setName("");
      setFeedUrl("");
      setMsg("Đã thêm quy tắc Kênh Autopilot.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo rule");
    }
  };

  const triggerRule = async (id: number) => {
    const res = await apiFetch<{ job_id: number }>(`/api/v1/autopilot/rules/${id}/trigger`, {
      method: "POST",
      body: JSON.stringify({ sync: false, force: true }),
    });
    setMsg(`Đã kích hoạt Autopilot Rule #${id} (Job #${res.job_id}).`);
  };

  const toggleRule = async (r: AutopilotRule) => {
    await apiFetch(`/api/v1/autopilot/rules/${r.id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled: !r.enabled }),
    });
    await load();
  };

  const removeRule = async (id: number) => {
    await apiFetch(`/api/v1/autopilot/rules/${id}`, { method: "DELETE" });
    await load();
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Bot className="w-6 h-6 text-emerald-400" /> Kênh Tự Chạy (Channel Autopilot)
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Tự động lấy bài RSS / Sản phẩm / Xu hướng → Render → QC → Tự xếp lịch nếu đạt điểm ngưỡng &amp; giới hạn daily_cap.
        </p>
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

      <form
        onSubmit={createRule}
        className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs"
      >
        <h2 className="text-sm font-semibold text-white">Tạo Quy Tắc Autopilot</h2>
        <div className="grid md:grid-cols-4 gap-3">
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Tên luồng tự chạy"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <select
            value={sourceMode}
            onChange={(e) => setSourceMode(e.target.value as AutopilotRule["source_mode"])}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="products_ab">Sản phẩm A/B</option>
            <option value="suggestions">Đề xuất Xu hướng</option>
            <option value="rss_feed">Nguồn RSS / Atom Feed</option>
            <option value="localize_trends">Việt hóa Xu hướng</option>
          </select>
          <input
            type="number"
            min={1}
            max={20}
            value={dailyCap}
            onChange={(e) => setDailyCap(Number(e.target.value))}
            placeholder="Giới hạn ngày"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <input
            type="number"
            step="0.1"
            min={1}
            max={10}
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value))}
            placeholder="Điểm tối thiểu auto-đăng"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
        </div>
        {sourceMode === "rss_feed" && (
          <input
            required
            value={feedUrl}
            onChange={(e) => setFeedUrl(e.target.value)}
            placeholder="URL RSS/Atom hoặc đường dẫn file .xml nội bộ..."
            className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
        )}
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold cursor-pointer"
        >
          Lưu Quy Tắc Autopilot
        </button>
      </form>

      <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3 text-xs">
        <h3 className="font-semibold text-white">Danh sách Quy tắc ({rules.length})</h3>
        {rules.map((r) => (
          <div
            key={r.id}
            className="bg-[#182235] border border-slate-700/70 rounded-lg p-3 flex items-center justify-between gap-3"
          >
            <div>
              <div className="font-semibold text-white">
                {r.name}{" "}
                <span className="text-[11px] text-sky-300 font-normal">
                  ({r.source_mode} • cap {r.daily_cap}/ngày • min {r.min_quality_score.toFixed(1)})
                </span>
              </div>
              <div className="text-[11px] text-slate-400">
                Trạng thái cuối: {r.last_status} • Đã sinh: {r.total_generated}
                {r.last_error ? ` • Lỗi: ${r.last_error}` : ""}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() => void toggleRule(r)}
                className={`px-2.5 py-1 rounded border cursor-pointer ${
                  r.enabled
                    ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-300"
                    : "bg-slate-800 border-slate-700 text-slate-400"
                }`}
              >
                {r.enabled ? "Đang bật" : "Đã tắt"}
              </button>
              <button
                type="button"
                onClick={() => void triggerRule(r.id)}
                className="px-2.5 py-1 rounded bg-sky-500/20 text-sky-300 cursor-pointer"
              >
                <Play className="w-3 h-3 inline mr-1" /> Chạy ngay
              </button>
              <button
                type="button"
                onClick={() => void removeRule(r.id)}
                className="text-slate-400 hover:text-rose-400 cursor-pointer"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-2 text-xs">
        <h3 className="font-semibold text-white">Nhật ký Chạy Autopilot ({runs.length})</h3>
        {runs.map((run) => (
          <div key={run.id} className="flex justify-between py-1.5 border-b border-slate-800/70">
            <span className="text-slate-300">
              Rule #{run.rule_id} • {run.source_summary || "—"} ({run.detail})
            </span>
            <span className="text-emerald-300">{run.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
