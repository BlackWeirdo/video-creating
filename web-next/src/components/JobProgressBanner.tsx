"use client";

import React, { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, X } from "lucide-react";
import { apiFetch, JobRecord } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

interface QueueSnapshotEventDetail {
  recent_jobs?: JobRecord[];
}

interface UseJobProgressOptions {
  onCompleted?: (job: JobRecord) => void;
  onFailed?: (job: JobRecord) => void;
  onStepChange?: (job: JobRecord) => void;
}

export function useJobProgress(
  activeJobId: number | null,
  options: UseJobProgressOptions = {}
) {
  const [job, setJob] = useState<JobRecord | null>(null);
  const optsRef = useRef(options);
  optsRef.current = options;
  const terminalNotifiedRef = useRef<string>("");
  const prevStepRef = useRef<string>("");

  useEffect(() => {
    if (!activeJobId) {
      setJob(null);
      terminalNotifiedRef.current = "";
      prevStepRef.current = "";
      return;
    }

    let cancelled = false;

    const applyUpdate = (next: JobRecord) => {
      if (cancelled || next.id !== activeJobId) return;
      setJob(next);

      if (next.step && next.step !== prevStepRef.current) {
        prevStepRef.current = next.step;
        optsRef.current.onStepChange?.(next);
      }

      const terminalKey = `${next.id}:${next.status}`;
      if (
        (next.status === "done" || next.status === "failed") &&
        terminalNotifiedRef.current !== terminalKey
      ) {
        terminalNotifiedRef.current = terminalKey;
        if (next.status === "done") {
          optsRef.current.onCompleted?.(next);
        } else {
          optsRef.current.onFailed?.(next);
        }
      }
    };

    const handleSseSnapshot = (ev: Event) => {
      const detail = (ev as CustomEvent<QueueSnapshotEventDetail>).detail;
      const found = detail?.recent_jobs?.find((j) => j.id === activeJobId);
      if (found) applyUpdate(found);
    };

    const pollOnce = async () => {
      try {
        const res = await apiFetch<{ job: JobRecord }>(`/api/v1/jobs/${activeJobId}`);
        if (res?.job) applyUpdate(res.job);
      } catch {
        // Ignore transient polling failures
      }
    };

    window.addEventListener("vc:queue-snapshot", handleSseSnapshot);
    void pollOnce();
    const timer = setInterval(() => {
      void pollOnce();
    }, 1500);

    return () => {
      cancelled = true;
      window.removeEventListener("vc:queue-snapshot", handleSseSnapshot);
      clearInterval(timer);
    };
  }, [activeJobId]);

  const isRunning = Boolean(
    activeJobId && (!job || job.status === "queued" || job.status === "running")
  );

  return { job, isRunning };
}

const STATUS_LABEL_VI: Record<string, string> = {
  queued: "Đang chờ tới lượt",
  running: "Đang xử lý",
  waiting_quota: "Tạm chờ hạn mức AI",
  done: "Hoàn tất",
  failed: "Gặp lỗi",
};

export function JobProgressBanner({
  job,
  jobId,
  label,
  onDismiss,
}: {
  job: JobRecord | null;
  jobId: number | null;
  label?: string;
  onDismiss?: () => void;
}) {
  if (!jobId) return null;

  const status = job?.status || "queued";
  const pct =
    status === "done"
      ? 100
      : Math.max(4, Math.min(99, Math.round((job?.progress || 0.04) * 100)));
  const stepText =
    job?.step ||
    (status === "queued"
      ? "Tác vụ đã vào hàng đợi xử lý nền..."
      : status === "done"
        ? "Tác vụ đã hoàn tất."
        : "Hệ thống đang xử lý...");

  const isDone = status === "done";
  const isFailed = status === "failed";
  const laneLabel = job?.lane === "io" ? "Tải & đăng" : "Xử lý video";

  return (
    <div
      role="status"
      aria-live="polite"
      className={`rounded-[13px] border px-4 py-3 text-[13px] space-y-2 ${
        isFailed
          ? "bg-[var(--st-rose-bg)] border-[var(--st-rose-bd)] text-[var(--st-rose-tx)]"
          : isDone
            ? "bg-[var(--st-emerald-bg)] border-[var(--st-emerald-bd)] text-[var(--st-emerald-tx)]"
            : "bg-[var(--bg-card)] border-[var(--c-bd)] text-[var(--text-primary)] shadow-[var(--shadow-sm)]"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 font-semibold">
          {isFailed ? (
            <AlertCircle className="w-4 h-4 shrink-0" />
          ) : isDone ? (
            <CheckCircle2 className="w-4 h-4 shrink-0" />
          ) : (
            <Loader2 className="w-4 h-4 text-[var(--c-icon)] animate-spin shrink-0" />
          )}
          <Badge tone={isFailed ? "rose" : isDone ? "emerald" : "cluster"} className="tabular-nums">
            {STATUS_LABEL_VI[status] || status} • {pct}%
          </Badge>
          <span>
            {label ? `${label} • ` : ""}Tác vụ #{jobId} ({laneLabel})
          </span>
        </div>
        {(isDone || isFailed) && onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Ẩn thanh tiến trình"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--text-muted)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)] cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      <div
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        className="w-full h-2 rounded-full bg-[var(--bg-elevated)] overflow-hidden"
      >
        <div
          className={`h-full transition-all duration-300 ${
            isFailed
              ? "bg-rose-500"
              : isDone
                ? "bg-emerald-500"
                : "bg-[var(--c-solid)]"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="text-[12.5px] text-[var(--text-secondary)] flex flex-wrap justify-between gap-2">
        <span>{stepText}</span>
        {isFailed && job?.error && (
          <span className="text-[var(--st-rose-tx)] font-semibold">{job.error}</span>
        )}
      </div>
    </div>
  );
}
