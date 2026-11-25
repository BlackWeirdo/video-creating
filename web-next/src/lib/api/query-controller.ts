export interface QueryControllerHandlers<T> {
  onSuccess: (data: T) => void;
  onError: (message: string) => void;
  onSettledLatest: () => void;
}

export function isAbortLike(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    "name" in err &&
    (err as { name?: unknown }).name === "AbortError"
  );
}

/**
 * Coordinates sequential or overlapping async queries (such as rapid Workspace switches),
 * aborting any in-flight `AbortController` and guaranteeing stale responses never overwrite newer state.
 */
export function createAbortableQueryRunner() {
  let current: AbortController | null = null;

  return {
    async run<T>(
      fetcher: (signal: AbortSignal) => Promise<T>,
      handlers: QueryControllerHandlers<T>,
      fallbackError = "Không thể tải dữ liệu"
    ): Promise<void> {
      current?.abort();
      const controller = new AbortController();
      current = controller;
      try {
        const result = await fetcher(controller.signal);
        if (controller.signal.aborted || current !== controller) return;
        handlers.onSuccess(result);
      } catch (err) {
        if (
          controller.signal.aborted ||
          current !== controller ||
          isAbortLike(err)
        ) {
          return;
        }
        handlers.onError(err instanceof Error ? err.message : fallbackError);
      } finally {
        if (current === controller) {
          handlers.onSettledLatest();
        }
      }
    },
    abort(): void {
      current?.abort();
      current = null;
    },
  };
}
