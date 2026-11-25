"use client";

import { useCallback, useState } from "react";
import { toast } from "sonner";
import { isAbortError } from "@/lib/api/client";

export interface UseApiMutationOptions<TResult> {
  fallbackError?: string;
  successMessage?: string | ((result: TResult) => string);
  onError?: (message: string) => void;
  onSuccess?: (result: TResult) => void | Promise<void>;
}

export function useApiMutation<TArgs extends unknown[], TResult = unknown>(
  mutationFn: (...args: TArgs) => Promise<TResult>,
  options?: UseApiMutationOptions<TResult>
) {
  const [mutating, setMutating] = useState(false);
  const [error, setError] = useState("");

  const mutate = useCallback(
    async (...args: TArgs): Promise<TResult | undefined> => {
      setMutating(true);
      setError("");
      try {
        const result = await mutationFn(...args);
        if (options?.successMessage) {
          const msg =
            typeof options.successMessage === "function"
              ? options.successMessage(result)
              : options.successMessage;
          if (msg) toast.success(msg);
        }
        await options?.onSuccess?.(result);
        return result;
      } catch (err) {
        if (isAbortError(err)) return undefined;
        const msg =
          err instanceof Error
            ? err.message
            : options?.fallbackError || "Thao tác thất bại";
        setError(msg);
        options?.onError?.(msg);
        return undefined;
      } finally {
        setMutating(false);
      }
    },
    [mutationFn, options]
  );

  return { mutate, mutating, error, setError };
}
