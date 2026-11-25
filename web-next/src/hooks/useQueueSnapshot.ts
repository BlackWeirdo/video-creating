"use client";

import { useEffect, useRef, useState } from "react";
import type { JobRecord, NavCounts, QueueSummary } from "@/lib/api/types";

export interface QueueSnapshotPayload {
  queue?: QueueSummary;
  recent_jobs?: JobRecord[];
  nav_counts?: NavCounts;
}

/**
 * Subscribes to the shared SSE window broadcast dispatched by `AppShell`.
 */
export function useQueueSnapshot(
  onSnapshot?: (snapshot: QueueSnapshotPayload) => void
): QueueSnapshotPayload | null {
  const [latest, setLatest] = useState<QueueSnapshotPayload | null>(null);
  const callbackRef = useRef(onSnapshot);
  callbackRef.current = onSnapshot;

  useEffect(() => {
    const handler = (ev: Event) => {
      const detail = (ev as CustomEvent<QueueSnapshotPayload>).detail;
      if (!detail) return;
      setLatest(detail);
      callbackRef.current?.(detail);
    };
    window.addEventListener("vc:queue-snapshot", handler);
    return () => window.removeEventListener("vc:queue-snapshot", handler);
  }, []);

  return latest;
}
