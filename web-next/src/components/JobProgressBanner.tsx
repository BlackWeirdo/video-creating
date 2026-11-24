"use client";

import React, { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, X } from "lucide-react";
import { apiFetch, JobRecord } from "@/lib/api";

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
      ? "Đang xếp hàng trong làn xử lý..."
      : status === "done"
        ? "Hoàn tất"
        : "Đang xử lý...");

  const isDone = status === "done";
  const isFailed = status === "failed";

  return (
    <div
      className={`border rounded-xl px-4 py-3 text-xs space-y-2 ${
        isFailed
          ? "bg-rose-500/10 border-rose-500/30 text-rose-200"
          : isDone
            ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-200"
            : "bg-sky-500/10 border-sky-500/30 text-sky-100"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-medium">
          {isFailed ? (
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
          ) : isDone ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
          ) : (
            <Loader2 className="w-4 h-4 text-sky-400 animate-spin shrink-0" />
          )}
          <span>
            {label ? `${label} • ` : ""}Job #{jobId} ({job?.lane || "compute"}):{" "}
            <strong className="uppercase">{status}</strong> — {pct}%
          </span>
        </div>
        {(isDone || isFailed) && onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className="text-slate-400 hover:text-white cursor-pointer"
            title="Ẩn thanh tiến trình"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      <div className="w-full h-2 rounded-full bg-slate-900/80 overflow-hidden">
        <div
          className={`h-full transition-all duration-300 ${
            isFailed
              ? "bg-rose-500"
              : isDone
                ? "bg-emerald-400"
                : "bg-sky-400"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="text-[11px] text-slate-300 flex flex-wrap justify-between gap-2">
        <span>{stepText}</span>
        {isFailed && job?.error && (
          <span className="text-rose-300 font-medium">{job.error}</span>
        )}
      </div>
    </div>
  );
}
