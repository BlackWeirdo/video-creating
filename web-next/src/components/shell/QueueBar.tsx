"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import { Activity, Monitor, Moon, Pause, Play, Sun, Terminal } from "lucide-react";
import { JobRecord, QueueSummary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
  }, []);

  const current = mounted ? theme || "system" : "system";
  const modes = [
    { key: "light", label: "Sáng", icon: Sun },
    { key: "dark", label: "Tối", icon: Moon },
    { key: "system", label: "Hệ thống", icon: Monitor },
  ] as const;

  return (
    <div
      role="group"
      aria-label="Chế độ giao diện Sáng hoặc Tối"
      className="inline-flex items-center gap-0.5 rounded-[9px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-0.5"
    >
      {modes.map((m) => {
        const Icon = m.icon;
        const active = current === m.key;
        return (
          <button
            key={m.key}
            type="button"
            onClick={() => setTheme(m.key)}
            className={cn(
              "inline-flex min-h-[29px] items-center gap-1.5 rounded-[6px] px-2.5 py-1 text-[12px] font-medium transition-colors cursor-pointer",
              active
                ? "bg-[var(--bg-card)] text-[var(--text-primary)] font-semibold shadow-[var(--shadow-sm)]"
                : "text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            )}
          >
            <Icon className="w-3.5 h-3.5" />
            <span>{m.label}</span>
          </button>
        );
      })}
    </div>
  );
}

const JOB_KIND_LABELS: Record<string, string> = {
  localize_extract: "Tách lời & Dịch",
  localize_render: "Xuất Việt hóa",
  scan_trends: "Quét xu hướng",
  trend_scan: "Quét xu hướng",
  render: "Xuất video",
  plan: "Lập kịch bản",
  batch_run: "Chạy hàng loạt",
  podcast_render: "Xuất Podcast",
  novel_render: "Xuất Truyện",
  news_render: "Xuất Tin tức",
  download_model: "Tải mô hình AI",
};

export function QueueBar({
  queue,
  recentJobs,
  showLogs,
  logLines,
  onTogglePause,
  onToggleLogs,
}: {
  queue: QueueSummary | null;
  recentJobs: JobRecord[];
  showLogs: boolean;
  logLines: string[];
  onTogglePause: () => void;
  onToggleLogs: () => void;
}) {
  const ioRunning = queue?.by_lane?.io?.running || 0;
  const computeRunning = queue?.by_lane?.compute?.running || 0;
  const totalQueued =
    (queue?.by_lane?.io?.queued || 0) + (queue?.by_lane?.compute?.queued || 0);
  const latestActiveJob =
    recentJobs.find((j) => j.status === "running") || recentJobs[0];

  const activeKindLabel = latestActiveJob
    ? JOB_KIND_LABELS[latestActiveJob.kind] || latestActiveJob.kind
    : "";

  return (
    <footer
      aria-label="Trạng thái tiến trình nền"
      className="sticky bottom-0 z-20 border-t border-[var(--border-subtle)] bg-[var(--bg-sidebar)]/94 backdrop-blur-md px-5 py-2"
    >
      <div className="flex items-center justify-between gap-3 text-[12.5px]">
        <div className="flex items-center gap-2 min-w-0 overflow-hidden">
          <span className="inline-flex items-center gap-1.5 font-semibold text-[var(--text-primary)] shrink-0">
            <Activity className="w-3.5 h-3.5 text-[var(--c-icon)]" />
            <span>Tiến trình nền:</span>
          </span>
          <span className="rounded-[8px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-2.5 py-0.5 text-[12px] whitespace-nowrap shrink-0 tabular-nums">
            Đang tải / đăng:{" "}
            <strong className="text-[var(--c-produce-icon)]">{ioRunning}</strong>
          </span>
          <span className="rounded-[8px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-2.5 py-0.5 text-[12px] whitespace-nowrap shrink-0 tabular-nums">
            Đang xử lý video:{" "}
            <strong className="text-[var(--c-icon)]">{computeRunning}</strong>
          </span>
          <span className="rounded-[8px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-2.5 py-0.5 text-[12px] whitespace-nowrap shrink-0 tabular-nums">
            Đang chờ: <strong>{totalQueued}</strong>
          </span>
          {latestActiveJob && (
            <span className="truncate text-[12px] text-[var(--text-muted)]">
              • #{latestActiveJob.id} ({activeKindLabel})
              {latestActiveJob.step ? ` — ${latestActiveJob.step}` : ""}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          <Button
            type="button"
            size="sm"
            variant={queue?.paused ? "emerald" : "amber"}
            onClick={onTogglePause}
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
          </Button>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={onToggleLogs}
          >
            <Terminal className="w-3.5 h-3.5" /> Nhật ký {showLogs ? "(Ẩn)" : ""}
          </Button>
        </div>
      </div>

      {showLogs && (
        <div className="mt-2 max-h-44 overflow-y-auto rounded-[9px] border border-[var(--border-strong)] bg-[var(--bg-input)] p-3 font-mono text-[11.5px] text-[var(--text-secondary)] space-y-0.5">
          {logLines.length === 0 ? (
            <div className="text-[var(--text-muted)]">Chưa có dòng nhật ký nào.</div>
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
  );
}
