"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { isAbortError } from "@/lib/api/client";

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

  const abortRef = useRef<AbortController | null>(null);
  const fetcherRef = useRef(fetcher);
  const optionsRef = useRef(options);
  fetcherRef.current = fetcher;
  optionsRef.current = options;

  const reload = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    try {
      const result = await fetcherRef.current(controller.signal);
      if (controller.signal.aborted) return;
      setData(result);
      setError("");
      optionsRef.current?.onSuccess?.(result);
    } catch (err) {
      if (controller.signal.aborted || isAbortError(err)) return;
      const fallback = optionsRef.current?.fallbackError || "Không thể tải dữ liệu";
      setError(err instanceof Error ? err.message : fallback);
    } finally {
      if (abortRef.current === controller) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void reload();
    return () => {
      abortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error, setError, reload };
}
