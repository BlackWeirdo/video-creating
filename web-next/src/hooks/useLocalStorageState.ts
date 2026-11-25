"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * SSR-safe `localStorage` state hook with JSON serialization.
 */
export function useLocalStorageState<T>(
  key: string,
  defaultValue: T
): [T, (next: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(defaultValue);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw !== null) {
        setValue(JSON.parse(raw) as T);
      }
    } catch {
      // Ignore storage access or parse errors
    }
  }, [key]);

  const update = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const resolved =
          typeof next === "function" ? (next as (p: T) => T)(prev) : next;
        try {
          window.localStorage.setItem(key, JSON.stringify(resolved));
        } catch {
          // Ignore quota or storage errors
        }
        return resolved;
      });
    },
    [key]
  );

  return [value, update];
}
