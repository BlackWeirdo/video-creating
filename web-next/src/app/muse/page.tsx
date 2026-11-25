"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Film, Image as ImageIcon, Layers, Settings, ShieldAlert, Sparkles } from "lucide-react";
import { apiFetch, CharacterOption, useWorkspace } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import { useQueueSnapshot } from "@/hooks/useQueueSnapshot";
import type {
  MuseCombo,
  MuseModelOption,
  MuseStatus,
  MuseStoryboard,
  MuseTask,
} from "@/app/muse/types";
import { CreateVideoAndVariantsCard } from "@/app/muse/_components/CreateVideoAndVariantsCard";
import { StoryboardPanel } from "@/app/muse/_components/StoryboardPanel";
import { MuseImageAndVoicePanel } from "@/app/muse/_components/MuseImageAndVoicePanel";
import { MuseQueueAndLibrary } from "@/app/muse/_components/MuseQueueAndLibrary";
import { PageHeader } from "@/components/vc/PageHeader";
import { PolicyBadge } from "@/components/vc/PolicyBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TabPanel, TabsBar, TabsRoot, TabTrigger } from "@/components/ui/overlays";

interface MusePageBundle {
  status: MuseStatus;
  tasks: MuseTask[];
  storyboards: MuseStoryboard[];
  models: MuseModelOption[];
  combos: MuseCombo[];
  characters: CharacterOption[];
  products: Array<{ id: number; name: string }>;
}

export default function MuseStudioPage() {
  const { activeWorkspaceId, activeWorkspace } = useWorkspace();
  const [liveRunning, setLiveRunning] = useState<number | null>(null);

  const { data, error: err, setError: setErr, reload } =
    useApiQuery<MusePageBundle>(
      async (signal) => {
        const [stRes, tRes, sbRes, mRes, cRes, pRes] = await Promise.all([
          apiFetch<MuseStatus>(
            `/api/v1/muse/status?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
          apiFetch<{ tasks: MuseTask[] }>(
            `/api/v1/muse/tasks?workspace_id=${activeWorkspaceId}&limit=80`,
            { signal }
          ),
          apiFetch<{ storyboards: MuseStoryboard[] }>(
            `/api/v1/muse/storyboards?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
          apiFetch<{ models: MuseModelOption[]; combos: MuseCombo[] }>(
            "/api/v1/muse/models",
            { signal }
          ).catch(() => ({ models: [], combos: [] })),
          apiFetch<{ characters: CharacterOption[] }>(
            `/api/v1/characters?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
          apiFetch<{ products: Array<{ id: number; name: string }> }>(
            `/api/v1/products?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
        ]);
        return {
          status: stRes,
          tasks: tRes.tasks || [],
          storyboards: sbRes.storyboards || [],
          models: mRes.models || [],
          combos: mRes.combos || [],
          characters: cRes.characters || [],
          products: pRes.products || [],
        };
      },
      [activeWorkspaceId],
      { fallbackError: "Không thể tải dữ liệu Muse Studio" }
    );

  useQueueSnapshot((snap) => {
    const rt = snap.muse_queue?.running_total;
    if (typeof rt === "number") {
      setLiveRunning((prev) => {
        if (prev !== null && prev !== rt) {
          void reload();
        }
        return rt;
      });
    }
  });

  const status = data?.status;
  const tasks = data?.tasks || [];
  const storyboards = data?.storyboards || [];
  const runningCount = liveRunning ?? status?.queue.running_total ?? 0;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        icon={<Sparkles className="w-5 h-5" />}
        title="Muse Studio — Tạo Video AI Đa Luồng & Storyboard"
        badges={
          <>
            <PolicyBadge policy={activeWorkspace?.content_policy} showDetail />
            <Badge tone={status?.online && status?.hardened ? "emerald" : "amber"}>
              {status?.online
                ? `Gateway Online (${status.accounts.ready}/${status.accounts.total} tài khoản sẵn sàng)`
                : "Gateway Offline"}
            </Badge>
            <Badge tone="cluster" className="tabular-nums">
              Đang chạy: {runningCount} • Năng lực: {status?.capacity ?? 0} luồng
            </Badge>
          </>
        }
        description="Điều phối tạo video song song trên nhiều tài khoản Muse (0 USD chi phí API), nối cảnh Storyboard tự động, sinh lô ảnh và giọng đọc WAV 48kHz."
        actions={
          <Button asChild variant="secondary">
            <Link href="/settings">
              <Settings className="w-4 h-4" /> Quản trị Tài khoản &amp; Pool Muse
            </Link>
          </Button>
        }
      />

      {status?.unsafe_error && (
        <div
          role="alert"
          className="rounded-[12px] border border-[var(--st-rose-bd)] bg-[var(--st-rose-bg)] p-4 text-[13px] text-[var(--st-rose-tx)] flex items-start gap-2.5"
        >
          <ShieldAlert className="w-5 h-5 shrink-0 mt-0.5" />
          <div>
            <div className="font-bold">Đã chặn Gateway chưa vá bảo mật (vc-hardened)</div>
            <div>{status.unsafe_error}</div>
          </div>
        </div>
      )}

      {err && (
        <div
          role="alert"
          className="rounded-[11px] border border-[var(--st-rose-bd)] bg-[var(--st-rose-bg)] px-4 py-2.5 text-[13px] text-[var(--st-rose-tx)]"
        >
          {err}
        </div>
      )}

      <TabsRoot defaultValue="video" className="space-y-4">
        <TabsBar aria-label="Chức năng Muse Studio">
          <TabTrigger value="video">
            <Sparkles className="w-4 h-4" /> Video &amp; Đa biến thể
          </TabTrigger>
          <TabTrigger value="storyboard">
            <Film className="w-4 h-4" /> Storyboard Nối Cảnh ({storyboards.length})
          </TabTrigger>
          <TabTrigger value="media">
            <ImageIcon className="w-4 h-4" /> Ảnh &amp; Giọng Muse
          </TabTrigger>
          <TabTrigger value="queue">
            <Layers className="w-4 h-4" /> Hàng Đợi &amp; Thư Viện ({tasks.length})
          </TabTrigger>
        </TabsBar>

        <TabPanel value="video">
          <div className="space-y-5">
            <CreateVideoAndVariantsCard
              workspaceId={activeWorkspaceId}
              contentPolicy={activeWorkspace?.content_policy}
              capacity={status?.capacity || 2}
              models={data?.models || []}
              combos={data?.combos || []}
              characters={data?.characters || []}
              products={data?.products || []}
              onCreated={reload}
              onError={setErr}
            />
            <MuseQueueAndLibrary tasks={tasks.slice(0, 8)} onReload={reload} onError={setErr} />
          </div>
        </TabPanel>

        <TabPanel value="storyboard">
          <StoryboardPanel
            workspaceId={activeWorkspaceId}
            contentPolicy={activeWorkspace?.content_policy}
            storyboards={storyboards}
            characters={data?.characters || []}
            onReload={reload}
            onError={setErr}
          />
        </TabPanel>

        <TabPanel value="media">
          <MuseImageAndVoicePanel
            workspaceId={activeWorkspaceId}
            onCreated={reload}
            onError={setErr}
          />
        </TabPanel>

        <TabPanel value="queue">
          <MuseQueueAndLibrary tasks={tasks} onReload={reload} onError={setErr} />
        </TabPanel>
      </TabsRoot>
    </div>
  );
}
