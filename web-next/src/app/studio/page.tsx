"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Check, RefreshCw, Sparkles } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";

interface StudioSession {
  id: number;
  video_id: number | null;
  prompt: string;
  status: string;
  cost_usd: number;
  error: string | null;
  created_at: string;
}

export default function StudioPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [sessions, setSessions] = useState<StudioSession[]>([]);
  const [prompt, setPrompt] = useState("");
  const [reviseMap, setReviseMap] = useState<Record<number, string>>({});
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<{ sessions: StudioSession[] }>(
        `/api/v1/studio/sessions?workspace_id=${activeWorkspaceId}`
      );
      setSessions(data.sessions || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải phiên Studio");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const startSession = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ session: StudioSession; job_id: number }>(
        "/api/v1/studio/sessions",
        {
          method: "POST",
          body: JSON.stringify({ workspace_id: activeWorkspaceId, prompt }),
        }
      );
      setPrompt("");
      setMsg(`Đã khởi chạy Studio Session #${res.session.id} (Job #${res.job_id}).`);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo phiên Studio");
    }
  };

  const confirmPlan = async (id: number) => {
    await apiFetch(`/api/v1/studio/sessions/${id}/confirm`, { method: "POST" });
    setMsg(`Đã xác nhận kịch bản Studio #${id}, bắt đầu render Remotion.`);
    await load();
  };

  const reviseSession = async (id: number) => {
    const rev = reviseMap[id] || "";
    if (!rev.trim()) return;
    await apiFetch(`/api/v1/studio/sessions/${id}/revise`, {
      method: "POST",
      body: JSON.stringify({ prompt: rev }),
    });
    setReviseMap((prev) => ({ ...prev, [id]: "" }));
    setMsg(`Đã gửi yêu cầu sửa cho Studio #${id}.`);
    await load();
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Sparkles className="w-6 h-6 text-purple-400" /> Remotion AI Code Studio
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Dựng motion graphic + JSX tùy biến trên footage thật, dừng xác nhận kịch bản trước khi render.
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
        onSubmit={startSession}
        className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs"
      >
        <label className="text-sm font-semibold text-white block">
          Tạo Phiên Studio Mới
        </label>
        <textarea
          required
          rows={3}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Mô tả phong cách chuyển cảnh, tiêu đề hook và bố cục mong muốn..."
          className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
        />
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
        >
          Chạy Phiên Studio
        </button>
      </form>

      <div className="space-y-3 text-xs">
        {sessions.map((s) => (
          <div
            key={s.id}
            className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-2.5"
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-white">
                Session #{s.id} (Video #{s.video_id ?? "—"})
              </span>
              <span className="px-2 py-0.5 rounded bg-slate-800 text-purple-300">
                {s.status} • ${s.cost_usd.toFixed(3)}
              </span>
            </div>
            <div className="text-slate-300">{s.prompt}</div>
            {s.error && <div className="text-rose-300">{s.error}</div>}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              {s.status === "awaiting_confirm" && (
                <button
                  onClick={() => void confirmPlan(s.id)}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-emerald-500 text-slate-950 font-semibold cursor-pointer"
                >
                  <Check className="w-3.5 h-3.5" /> Xác nhận & Render
                </button>
              )}
              {["awaiting_confirm", "done", "failed"].includes(s.status) && (
                <div className="flex flex-1 gap-2 min-w-60">
                  <input
                    value={reviseMap[s.id] || ""}
                    onChange={(e) =>
                      setReviseMap((prev) => ({ ...prev, [s.id]: e.target.value }))
                    }
                    placeholder="Nhập yêu cầu chỉnh sửa..."
                    className="flex-1 bg-[#182235] border border-slate-700 rounded px-2.5 py-1.5"
                  />
                  <button
                    onClick={() => void reviseSession(s.id)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-slate-800 text-sky-300 border border-slate-700 cursor-pointer"
                  >
                    <RefreshCw className="w-3 h-3" /> Sửa lại
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
