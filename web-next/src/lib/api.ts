"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";

export interface Workspace {
  id: number;
  slug: string;
  name: string;
  niche: string;
  content_policy: "strict_footage" | "hybrid_remix" | "full_ai";
  approval_mode: "single" | "bulk" | "autopilot";
  default_aspect_ratio: "9:16" | "16:9" | "1:1";
  style_preset: string;
  archived: boolean;
}

export interface QueueSummary {
  paused: boolean;
  by_status: Record<string, number>;
  by_lane: {
    io: Record<string, number>;
    compute: Record<string, number>;
  };
}

export interface JobRecord {
  id: number;
  workspace_id: number;
  kind: string;
  lane: "io" | "compute";
  status: string;
  progress: number;
  step: string;
  attempts?: number;
  error: string | null;
  log_tail: string | null;
}

export interface NavCounts {
  approvals_pending: number;
  suggestions_new: number;
  failed_routes: string[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export async function parseApiResponse<T = unknown>(res: Response): Promise<T> {
  const rawText = await res.text();
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    let detail: unknown = rawText;
    if (rawText) {
      try {
        const errBody = JSON.parse(rawText) as { detail?: unknown };
        if (errBody && errBody.detail !== undefined) {
          detail = errBody.detail;
          msg =
            typeof errBody.detail === "string"
              ? errBody.detail
              : JSON.stringify(errBody.detail);
        } else {
          msg = rawText.slice(0, 200);
        }
      } catch {
        msg = rawText.slice(0, 200);
      }
    }
    throw new ApiError(res.status, msg, detail);
  }

  if (res.status === 204 || !rawText.trim()) {
    return undefined as T;
  }
  return JSON.parse(rawText) as T;
}

export async function apiFetch<T = unknown>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const isFormData =
    typeof FormData !== "undefined" && options?.body instanceof FormData;
  const headers: Record<string, string> = isFormData
    ? {}
    : { "Content-Type": "application/json" };

  if (options?.headers) {
    Object.assign(headers, options.headers as Record<string, string>);
  }

  const res = await fetch(path, {
    ...options,
    headers,
    cache: "no-store",
  });

  return parseApiResponse<T>(res);
}

interface WorkspaceContextValue {
  workspaces: Workspace[];
  activeWorkspaceId: number;
  activeWorkspace: Workspace | null;
  loading: boolean;
  refreshWorkspaces: () => Promise<void>;
  activateWorkspace: (id: number) => Promise<void>;
}

const WorkspaceContext = createContext<WorkspaceContextValue>({
  workspaces: [],
  activeWorkspaceId: 1,
  activeWorkspace: null,
  loading: true,
  refreshWorkspaces: async () => {},
  activateWorkspace: async () => {},
});

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<number>(1);
  const [loading, setLoading] = useState<boolean>(true);

  const refreshWorkspaces = useCallback(async () => {
    try {
      const data = await apiFetch<{
        workspaces: Workspace[];
        active_workspace_id: number;
      }>("/api/v1/workspaces");
      setWorkspaces(data.workspaces || []);
      setActiveWorkspaceId(data.active_workspace_id || 1);
    } catch {
      // Backend might still be warming up on first boot
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshWorkspaces();
  }, [refreshWorkspaces]);

  const activateWorkspace = useCallback(async (id: number) => {
    const data = await apiFetch<{
      active_workspace_id: number;
      workspace: Workspace;
    }>(`/api/v1/workspaces/${id}/activate`, { method: "POST" });
    setActiveWorkspaceId(data.active_workspace_id);
    await refreshWorkspaces();
  }, [refreshWorkspaces]);

  const activeWorkspace =
    workspaces.find((w) => w.id === activeWorkspaceId) || workspaces[0] || null;

  return React.createElement(
    WorkspaceContext.Provider,
    {
      value: {
        workspaces,
        activeWorkspaceId,
        activeWorkspace,
        loading,
        refreshWorkspaces,
        activateWorkspace,
      },
    },
    children
  );
}

export function useWorkspace(): WorkspaceContextValue {
  return useContext(WorkspaceContext);
}
