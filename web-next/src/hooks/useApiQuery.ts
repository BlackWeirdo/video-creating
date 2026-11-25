"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { createAbortableQueryRunner } from "@/lib/api/query-controller";

export interface UseApiQueryOptions<T> {
  fallbackError?: string;
  onSuccess?: (data: T) => void;
}

export interface UseApiQueryResult<T> {
  data: T | null;
  loading: boolean;
  error: string;
  setError: React.Dispatch<React.SetStateAction<string>>;
  reload: () => Promise<void>;
}

/**
 * Workspace-safe async query hook that cancels stale in-flight requests via
 * `AbortController` whenever dependencies (e.g. `activeWorkspaceId`) change.
 */
export function useApiQuery<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: React.DependencyList,
  options?: UseApiQueryOptions<T>
): UseApiQueryResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");

  const runnerRef = useRef<ReturnType<typeof createAbortableQueryRunner> | null>(
    null
  );
  if (!runnerRef.current) {
    runnerRef.current = createAbortableQueryRunner();
  }

  const fetcherRef = useRef(fetcher);
  const optionsRef = useRef(options);
  fetcherRef.current = fetcher;
  optionsRef.current = options;

  const reload = useCallback(async () => {
    setLoading(true);
    await runnerRef.current!.run(
      (signal) => fetcherRef.current(signal),
      {
        onSuccess: (result) => {
          setData(result);
          setError("");
          optionsRef.current?.onSuccess?.(result);
        },
        onError: (msg) => {
          setError(msg);
        },
        onSettledLatest: () => {
          setLoading(false);
        },
      },
      optionsRef.current?.fallbackError || "Không thể tải dữ liệu"
    );
  }, []);

  useEffect(() => {
    void reload();
    const runner = runnerRef.current!;
    return () => {
      runner.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error, setError, reload };
}
