"use client";

import React, { useState } from "react";
import { BookOpen } from "lucide-react";
import { toast } from "sonner";
import {
  apiFetch,
  ChannelVoiceOption,
  CharacterOption,
  useWorkspace,
} from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import type { NovelProject } from "@/app/novel/types";
import { CreateNovelCard } from "@/app/novel/_components/CreateNovelCard";
import { NovelProjectsList } from "@/app/novel/_components/NovelProjectsList";
import { JobProgressBanner, useJobProgress } from "@/components/JobProgressBanner";
import { PageHeader } from "@/components/vc/PageHeader";
import { Badge } from "@/components/ui/badge";

interface NovelPageBundle {
  projects: NovelProject[];
  characters: CharacterOption[];
  channelVoices: ChannelVoiceOption[];
}

export default function NovelStudioPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [renderingId, setRenderingId] = useState<number | null>(null);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");

  const { data, error: err, setError: setErr, reload: load } =
    useApiQuery<NovelPageBundle>(
      async (signal) => {
        const [res, cRes, cvRes] = await Promise.all([
          apiFetch<{ projects: NovelProject[] }>(
            `/api/v1/novels/projects?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
          apiFetch<{ characters: CharacterOption[] }>(
            `/api/v1/characters?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
          apiFetch<{ channel_voices: ChannelVoiceOption[] }>(
            `/api/v1/channel-voices?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
        ]);
        return {
          projects: res.projects || [],
          characters: cRes.characters || [],
          channelVoices: cvRes.channel_voices || [],
        };
      },
      [activeWorkspaceId],
      { fallbackError: "Lỗi tải Studio Truyện" }
    );

  const projects = data?.projects || [];
  const characters = data?.characters || [];
  const channelVoices = data?.channelVoices || [];

  const { job: activeJob, isRunning: jobRunning } = useJobProgress(activeJobId, {
    onStepChange: () => {
      void load();
    },
    onCompleted: () => {
      const done = `Đã xuất xong các chương cho bộ truyện #${renderingId ?? ""}.`;
      setMsg(done);
      toast.success(done);
      setRenderingId(null);
      void load();
    },
    onFailed: (j) => {
      setErr(j.error || "Lỗi xuất chương truyện");
      setRenderingId(null);
      void load();
    },
  });

  const renderProject = async (pid: number, force = false) => {
    setRenderingId(pid);
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ job_id: number }>(
        `/api/v1/novels/projects/${pid}/render`,
        {
          method: "POST",
          body: JSON.stringify({ sync: false, force }),
        }
      );
      setActiveJobId(res.job_id);
      const m = `Đã đưa các chương truyện #${pid} vào hàng đợi xuất video (Tác vụ #${res.job_id}).`;
      setMsg(m);
      toast.info(m);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi xuất chương truyện");
      setRenderingId(null);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <PageHeader
        icon={<BookOpen className="w-5 h-5" />}
        title="Truyện & Tiểu Thuyết Đa Chương → Video"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {projects.length} bộ truyện
          </Badge>
        }
        description="Tự động chia chương vừa thời lượng Shorts / YouTube, lồng tiếng đọc truyện tự nhiên và phục hồi thông minh từ đúng chương còn dở."
      />

      {msg && (
        <div
          role="status"
          className="rounded-[11px] border border-[var(--st-emerald-bd)] bg-[var(--st-emerald-bg)] px-4 py-2.5 text-[13px] text-[var(--st-emerald-tx)]"
        >
          {msg}
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

      <JobProgressBanner
        job={activeJob}
        jobId={activeJobId}
        label={renderingId ? `Bộ truyện #${renderingId}` : "Studio Truyện"}
        onDismiss={() => setActiveJobId(null)}
      />

      <CreateNovelCard
        workspaceId={activeWorkspaceId}
        characters={characters}
        channelVoices={channelVoices}
        onReload={load}
        onMessage={setMsg}
        onError={setErr}
      />

      <NovelProjectsList
        projects={projects}
        jobRunning={jobRunning}
        renderingId={renderingId}
        onRender={renderProject}
      />
    </div>
  );
}
