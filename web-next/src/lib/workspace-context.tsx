"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { apiFetch } from "@/lib/api/client";
import type { Workspace } from "@/lib/api/types";

export interface WorkspaceContextValue {
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

  const activateWorkspace = useCallback(
    async (id: number) => {
      const data = await apiFetch<{
        active_workspace_id: number;
        workspace: Workspace;
      }>(`/api/v1/workspaces/${id}/activate`, { method: "POST" });
      setActiveWorkspaceId(data.active_workspace_id);
      await refreshWorkspaces();
    },
    [refreshWorkspaces]
  );

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
