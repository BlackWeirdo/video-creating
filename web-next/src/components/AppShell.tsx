"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Rocket } from "lucide-react";
import { apiFetch, JobRecord, NavCounts, QueueSummary } from "@/lib/api";
import { resolveRouteMeta, STORAGE_KEYS } from "@/config/navigation";
import { Sidebar } from "@/components/shell/Sidebar";
import { CreateWorkspaceDialog } from "@/components/shell/WorkspaceSwitcher";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { QueueBar, ThemeToggle } from "@/components/shell/QueueBar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const routeMeta = resolveRouteMeta(pathname);

  const [queue, setQueue] = useState<QueueSummary | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobRecord[]>([]);
  const [navCounts, setNavCounts] = useState<NavCounts | null>(null);
  const [museRunning, setMuseRunning] = useState(0);
  const [showLogs, setShowLogs] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [wizardNeeded, setWizardNeeded] = useState(false);
  const [showNewWs, setShowNewWs] = useState(false);
  const [cmdkOpen, setCmdkOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [manualCollapsed, setManualCollapsed] = useState<boolean | null>(null);

  // Sync active cluster attribute on <html> so portaled dialogs/dropdowns share cluster tokens
  useEffect(() => {
    document.documentElement.setAttribute("data-cluster", routeMeta.clusterId);
  }, [routeMeta.clusterId]);

  const syncSidebarPref = useCallback(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.SIDEBAR_COLLAPSED);
      if (saved === "1" || saved === "0") {
        const flag = saved === "1";
        setManualCollapsed(flag);
        setCollapsed(flag);
        return;
      }
      setManualCollapsed(null);
      setCollapsed(window.innerWidth < 1100);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    syncSidebarPref();
    const onResize = () => {
      if (manualCollapsed === null) {
        setCollapsed(window.innerWidth < 1100);
      }
    };
    window.addEventListener("resize", onResize);
    window.addEventListener("vc:nav-prefs-changed", syncSidebarPref);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("vc:nav-prefs-changed", syncSidebarPref);
    };
  }, [manualCollapsed, syncSidebarPref]);

  const handleToggleCollapse = () => {
    const next = !collapsed;
    setManualCollapsed(next);
    setCollapsed(next);
    try {
      localStorage.setItem(STORAGE_KEYS.SIDEBAR_COLLAPSED, next ? "1" : "0");
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    const checkWizard = () => {
      void apiFetch<{ wizard_completed: boolean }>("/api/v1/onboarding/status")
        .then((res) => setWizardNeeded(!res.wizard_completed))
        .catch(() => {});
    };
    checkWizard();
    window.addEventListener("vc:onboarding-updated", checkWizard);
    return () => window.removeEventListener("vc:onboarding-updated", checkWizard);
  }, []);

  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource("/api/v1/events");
      es.addEventListener("queue_snapshot", (ev) => {
        try {
          const snap = JSON.parse((ev as MessageEvent<string>).data);
          if (snap?.queue) setQueue(snap.queue);
          if (Array.isArray(snap?.recent_jobs)) setRecentJobs(snap.recent_jobs);
          if (snap?.nav_counts) setNavCounts(snap.nav_counts);
          if (typeof snap?.muse_queue?.running_total === "number") {
            setMuseRunning(snap.muse_queue.running_total);
          }
          window.dispatchEvent(new CustomEvent("vc:queue-snapshot", { detail: snap }));
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

  return (
    <div
      data-cluster={routeMeta.clusterId}
      style={{
        background:
          "radial-gradient(640px 320px at 0% 0%, var(--c-soft), transparent 70%), var(--bg-canvas)",
      }}
      className="min-h-screen flex text-[var(--text-primary)]"
    >
      <a
        href="#main-studio-content"
        className="fixed -top-28 left-4 z-50 rounded-lg bg-[var(--c-solid)] px-3.5 py-2 text-[13px] font-semibold text-[var(--c-on)] focus:top-3"
      >
        Bỏ qua tới nội dung chính
      </a>

      <Sidebar
        collapsed={collapsed}
        onToggleCollapse={handleToggleCollapse}
        onOpenCmdk={() => setCmdkOpen(true)}
        onOpenCreateWs={() => setShowNewWs(true)}
        wizardNeeded={wizardNeeded}
        navCounts={navCounts}
        museRunning={museRunning}
      />

      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Breadcrumb + Theme Switcher */}
        <header className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] bg-[var(--bg-canvas)]/86 backdrop-blur-md px-6 py-2.5">
          <div
            aria-label="Vị trí hiện tại"
            className="flex items-center gap-2 text-[13px] text-[var(--text-muted)]"
          >
            <Badge tone="cluster">{routeMeta.clusterLabel}</Badge>
            <span aria-hidden="true">/</span>
            <span className="font-semibold text-[var(--text-primary)]">
              {routeMeta.itemLabel}
            </span>
          </div>
          <ThemeToggle />
        </header>

        {wizardNeeded && pathname !== "/welcome" && (
          <div className="border-b border-[var(--c-bd)] bg-[var(--c-soft)] px-6 py-2 flex flex-wrap items-center justify-between gap-2 text-[13px]">
            <span className="text-[var(--text-primary)] font-medium">
              Chào mừng bạn đến Video Creator V2! Hãy hoàn tất Hướng dẫn thiết lập để kiểm tra FFmpeg, Workspace &amp; AI Keys.
            </span>
            <Button asChild size="sm">
              <Link href="/welcome">
                <Rocket className="w-3.5 h-3.5" /> Thiết lập ngay →
              </Link>
            </Button>
          </div>
        )}

        <main
          id="main-studio-content"
          className="flex-1 px-6 py-5 pb-20 overflow-y-auto"
        >
          {children}
        </main>

        <QueueBar
          queue={queue}
          recentJobs={recentJobs}
          showLogs={showLogs}
          logLines={logLines}
          onTogglePause={() => void togglePause()}
          onToggleLogs={() => setShowLogs((v) => !v)}
        />
      </div>

      <CreateWorkspaceDialog open={showNewWs} onOpenChange={setShowNewWs} />
      <CommandPalette
        open={cmdkOpen}
        onOpenChange={setCmdkOpen}
        queuePaused={Boolean(queue?.paused)}
        onTogglePause={() => void togglePause()}
        onToggleLogs={() => setShowLogs((v) => !v)}
        onOpenCreateWs={() => setShowNewWs(true)}
      />
    </div>
  );
}
