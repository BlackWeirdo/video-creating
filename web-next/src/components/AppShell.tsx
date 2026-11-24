"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Bot,
  CheckCircle2,
  Clapperboard,
  Film,
  Flame,
  FolderKanban,
  Languages,
  Layers,
  LayoutDashboard,
  Palette,
  Pause,
  Play,
  Plus,
  Settings,
  ShieldCheck,
  Sparkles,
  Terminal,
  X,
} from "lucide-react";
import { apiFetch, JobRecord, QueueSummary, useWorkspace, Workspace } from "@/lib/api";

const NAV_ITEMS = [
  { href: "/", label: "Tổng quan", icon: LayoutDashboard },
  { href: "/trends", label: "Xu hướng & Công thức", icon: Flame },
  { href: "/products", label: "Sản phẩm & Dữ kiện", icon: FolderKanban },
  { href: "/footage", label: "Footage & Kho Shot", icon: Film },
  { href: "/videos", label: "Sản xuất & Kịch bản", icon: Clapperboard },
  { href: "/localize", label: "Việt hóa & Remix", icon: Languages },
  { href: "/batch", label: "Batch & A/B Studio", icon: Layers },
  { href: "/video-style", label: "Video Style & Audio", icon: Palette },
  { href: "/studio", label: "Remotion Studio AI", icon: Sparkles },
  { href: "/autopilot", label: "Kênh Autopilot", icon: Bot },
  { href: "/approval", label: "Duyệt, Kênh & Lịch đăng", icon: CheckCircle2 },
  { href: "/settings", label: "Cài đặt & AI Keys", icon: Settings },
];

const POLICY_BADGE: Record<Workspace["content_policy"], { label: string; cls: string }> = {
  strict_footage: {
    label: "Strict Footage",
    cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  },
  hybrid_remix: {
    label: "Hybrid Remix",
    cls: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  },
  full_ai: {
    label: "Full AI",
    cls: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  },
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const {
    workspaces,
    activeWorkspaceId,
    activeWorkspace,
    refreshWorkspaces,
    activateWorkspace,
  } = useWorkspace();

  const [queue, setQueue] = useState<QueueSummary | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobRecord[]>([]);
  const [showLogs, setShowLogs] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [showNewWs, setShowNewWs] = useState(false);

  const [wsName, setWsName] = useState("");
  const [wsNiche, setWsNiche] = useState("general");
  const [wsPolicy, setWsPolicy] = useState<Workspace["content_policy"]>("strict_footage");
  const [wsApproval, setWsApproval] = useState<Workspace["approval_mode"]>("single");
  const [wsRatio, setWsRatio] = useState<Workspace["default_aspect_ratio"]>("9:16");
  const [wsErr, setWsErr] = useState("");

  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource("/api/v1/events");
      es.addEventListener("queue_snapshot", (ev) => {
        try {
          const snap = JSON.parse((ev as MessageEvent<string>).data);
          if (snap?.queue) setQueue(snap.queue);
          if (Array.isArray(snap?.recent_jobs)) setRecentJobs(snap.recent_jobs);
        } catch {
          // ignore malformed heartbeat
        }
      });
    } catch {
      // ignore if EventSource unavailable
    }
    return () => {
      es?.close();
    };
  }, []);

  const loadLogTail = async () => {
    try {
      const data = await apiFetch<{ lines: string[] }>("/api/v1/logs/tail?lines=80");
      setLogLines(data.lines || []);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    if (!showLogs) return;
    void loadLogTail();
    const t = setInterval(() => void loadLogTail(), 3000);
    return () => clearInterval(t);
  }, [showLogs]);

  const togglePause = async () => {
    if (!queue) return;
    const ep = queue.paused ? "/api/v1/queue/resume" : "/api/v1/queue/pause";
    const next = await apiFetch<QueueSummary>(ep, { method: "POST" });
    setQueue(next);
  };

  const handleCreateWorkspace = async (e: React.FormEvent) => {
    e.preventDefault();
    setWsErr("");
    try {
      const res = await apiFetch<{ workspace: Workspace }>("/api/v1/workspaces", {
        method: "POST",
        body: JSON.stringify({
          name: wsName,
          niche: wsNiche,
          content_policy: wsPolicy,
          approval_mode: wsApproval,
          default_aspect_ratio: wsRatio,
        }),
      });
      await activateWorkspace(res.workspace.id);
      setWsName("");
      setShowNewWs(false);
    } catch (err) {
      setWsErr(err instanceof Error ? err.message : "Không thể tạo Workspace");
    }
  };

  const policyBadge = activeWorkspace
    ? POLICY_BADGE[activeWorkspace.content_policy]
    : POLICY_BADGE.strict_footage;

  const ioRunning = queue?.by_lane?.io?.running || 0;
  const ioQueued = queue?.by_lane?.io?.queued || 0;
  const computeRunning = queue?.by_lane?.compute?.running || 0;
  const computeQueued = queue?.by_lane?.compute?.queued || 0;
  const latestActiveJob = recentJobs.find((j) => j.status === "running") || recentJobs[0];

  return (
    <div className="min-h-screen flex bg-[#0b0f17] text-slate-100">
      {/* Left Studio Sidebar */}
      <aside className="w-68 shrink-0 bg-[#111827] border-r border-slate-800/80 flex flex-col justify-between">
        <div>
          <div className="px-4 py-4 border-b border-slate-800/80 flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-sky-500/20 border border-sky-400/30 flex items-center justify-center text-sky-400">
              <Layers className="w-4 h-4" />
            </div>
            <div>
              <div className="font-semibold text-sm tracking-tight text-white">
                Video Creator V2
              </div>
              <div className="text-[11px] text-slate-400">AI Multi-Studio Desktop</div>
            </div>
          </div>

          {/* Workspace Switcher */}
          <div className="p-3 border-b border-slate-800/80 space-y-2">
            <div className="flex items-center justify-between text-[11px] uppercase tracking-wider text-slate-400 px-1">
              <span>Workspace thương hiệu</span>
              <button
                onClick={() => setShowNewWs(true)}
                className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-300 cursor-pointer"
                title="Tạo Workspace mới"
              >
                <Plus className="w-3.5 h-3.5" /> Tạo mới
              </button>
            </div>
            <select
              value={activeWorkspaceId}
              onChange={(e) => void activateWorkspace(Number(e.target.value))}
              className="w-full bg-[#182235] border border-slate-700/80 rounded-lg px-2.5 py-2 text-xs text-slate-100 focus:outline-none focus:border-sky-400"
            >
              {workspaces.map((ws) => (
                <option key={ws.id} value={ws.id}>
                  {ws.name} ({ws.niche})
                </option>
              ))}
            </select>
            {activeWorkspace && (
              <div className="flex flex-wrap gap-1.5 px-0.5">
                <span
                  className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border ${policyBadge.cls}`}
                >
                  <ShieldCheck className="w-3 h-3" /> {policyBadge.label}
                </span>
                <span className="inline-flex items-center text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
                  Duyệt: {activeWorkspace.approval_mode}
                </span>
              </div>
            )}
          </div>

          {/* Navigation */}
          <nav className="p-2.5 space-y-1">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive =
                item.href === "/"
                  ? pathname === "/"
                  : pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                    isActive
                      ? "bg-sky-500/15 text-sky-300 border border-sky-500/30"
                      : "text-slate-300 hover:bg-slate-800/70 hover:text-white border border-transparent"
                  }`}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="p-3 border-t border-slate-800/80 text-[11px] text-slate-500">
          FastAPI + Dual-Lane Worker • Next.js 15
        </div>
      </aside>

      {/* Main Content + Persistent Queue Bar */}
      <div className="flex-1 flex flex-col min-w-0">
        <main className="flex-1 p-6 pb-20 overflow-y-auto">{children}</main>

        {/* Bottom Live Dual-Lane Queue & Logs Bar */}
        <footer className="sticky bottom-0 z-20 bg-[#111827]/95 backdrop-blur border-t border-slate-800 px-5 py-2.5">
          <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-1.5">
                <Activity className="w-3.5 h-3.5 text-sky-400" />
                <span className="text-slate-300 font-medium">Hàng đợi 2 làn:</span>
              </div>
              <span className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-200">
                Làn IO: <strong className="text-sky-300">{ioRunning}</strong> chạy /{" "}
                {ioQueued} chờ
              </span>
              <span className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-200">
                Làn Compute: <strong className="text-amber-300">{computeRunning}</strong> chạy
                / {computeQueued} chờ
              </span>
              {latestActiveJob && (
                <span className="text-slate-400 truncate max-w-xs">
                  Job #{latestActiveJob.id} ({latestActiveJob.kind}):{" "}
                  <span className="text-slate-200">{latestActiveJob.status}</span>
                  {latestActiveJob.step ? ` — ${latestActiveJob.step}` : ""}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => void togglePause()}
                className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-md font-medium border cursor-pointer ${
                  queue?.paused
                    ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                    : "bg-amber-500/15 text-amber-300 border-amber-500/30"
                }`}
              >
                {queue?.paused ? (
                  <>
                    <Play className="w-3.5 h-3.5" /> Chạy tiếp
                  </>
                ) : (
                  <>
                    <Pause className="w-3.5 h-3.5" /> Tạm dừng
                  </>
                )}
              </button>
              <button
                onClick={() => setShowLogs((v) => !v)}
                className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 cursor-pointer"
              >
                <Terminal className="w-3.5 h-3.5" /> Logs ({showLogs ? "Ẩn" : "Mở"})
              </button>
            </div>
          </div>

          {showLogs && (
            <div className="mt-2.5 bg-[#090d14] border border-slate-800 rounded-lg p-3 max-h-48 overflow-y-auto font-mono text-[11px] text-slate-300 space-y-0.5">
              {logLines.length === 0 ? (
                <div className="text-slate-500">Chưa có dòng log nào.</div>
              ) : (
                logLines.map((line, i) => (
                  <div key={i} className="whitespace-pre-wrap break-all">
                    {line}
                  </div>
                ))
              )}
            </div>
          )}
        </footer>
      </div>

      {/* Create Workspace Modal */}
      {showNewWs && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
          <form
            onSubmit={handleCreateWorkspace}
            className="w-full max-w-md bg-[#111827] border border-slate-700 rounded-xl p-5 space-y-4 shadow-2xl"
          >
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-base">Tạo Workspace Mới</h3>
              <button
                type="button"
                onClick={() => setShowNewWs(false)}
                className="text-slate-400 hover:text-white cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            {wsErr && (
              <div className="text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded px-3 py-2">
                {wsErr}
              </div>
            )}
            <div className="space-y-1">
              <label className="text-xs text-slate-300">Tên thương hiệu / Dự án</label>
              <input
                required
                value={wsName}
                onChange={(e) => setWsName(e.target.value)}
                placeholder="VD: Trang Sức Bạc S925"
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-slate-300">Ngành hàng</label>
                <input
                  value={wsNiche}
                  onChange={(e) => setWsNiche(e.target.value)}
                  className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2 text-sm"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-slate-300">Khung hình ưu tiên</label>
                <select
                  value={wsRatio}
                  onChange={(e) =>
                    setWsRatio(e.target.value as Workspace["default_aspect_ratio"])
                  }
                  className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2 text-sm"
                >
                  <option value="9:16">9:16 (Dọc Shorts/Reels)</option>
                  <option value="16:9">16:9 (Ngang YouTube)</option>
                  <option value="1:1">1:1 (Vuông)</option>
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-slate-300">Kiểm soát nội dung</label>
                <select
                  value={wsPolicy}
                  onChange={(e) =>
                    setWsPolicy(e.target.value as Workspace["content_policy"])
                  }
                  className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2 text-sm"
                >
                  <option value="strict_footage">Strict Footage (Chuẩn hãng)</option>
                  <option value="hybrid_remix">Hybrid Remix</option>
                  <option value="full_ai">Full AI (Kênh vệ tinh)</option>
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-slate-300">Chế độ duyệt</label>
                <select
                  value={wsApproval}
                  onChange={(e) =>
                    setWsApproval(e.target.value as Workspace["approval_mode"])
                  }
                  className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2 text-sm"
                >
                  <option value="single">Duyệt từng bài</option>
                  <option value="bulk">Duyệt hàng loạt</option>
                  <option value="autopilot">Autopilot tự đăng</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowNewWs(false)}
                className="px-4 py-2 text-xs rounded-lg bg-slate-800 text-slate-300 cursor-pointer"
              >
                Hủy
              </button>
              <button
                type="submit"
                className="px-4 py-2 text-xs rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
              >
                Tạo & Chuyển ngay
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
