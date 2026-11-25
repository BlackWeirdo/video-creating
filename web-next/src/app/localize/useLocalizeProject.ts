"use client";

import { useState } from "react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import { useJobProgress } from "@/components/JobProgressBanner";
import {
  LocalizeProject,
  LocalizeSegment,
  ShotRow,
  SpeakerEntry,
} from "@/app/localize/types";

export function useLocalizeProject() {
  const { activeWorkspaceId, activeWorkspace } = useWorkspace();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [previewAudioMap, setPreviewAudioMap] = useState<Record<string, string>>({});
  const [previewLoadingKey, setPreviewLoadingKey] = useState<string | null>(null);
  const [showBoxPreview, setShowBoxPreview] = useState(false);
  const [cloneModalOpen, setCloneModalOpen] = useState(false);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");

  const wsPolicy = activeWorkspace?.content_policy || "strict_footage";
  const canCloneVoice = wsPolicy === "hybrid_remix" || wsPolicy === "full_ai";

  const { data, error: err, setError: setErr, reload: load } = useApiQuery<{
    projects: LocalizeProject[];
    shots: ShotRow[];
  }>(
    async (signal) => {
      const [pRes, sRes] = await Promise.all([
        apiFetch<{ projects: LocalizeProject[] }>(
          `/api/v1/localize/projects?workspace_id=${activeWorkspaceId}`,
          { signal }
        ),
        apiFetch<{ shots: ShotRow[] }>(
          `/api/v1/shots?workspace_id=${activeWorkspaceId}`,
          { signal }
        ),
      ]);
      return {
        projects: pRes.projects || [],
        shots: sRes.shots || [],
      };
    },
    [activeWorkspaceId],
    {
      fallbackError: "Lỗi tải Studio Việt hóa",
      onSuccess: (bundle) => {
        setSelectedId((prev) =>
          bundle.projects.some((p) => p.id === prev)
            ? prev
            : bundle.projects[0]?.id ?? null
        );
      },
    }
  );

  const projects = data?.projects || [];
  const shots = data?.shots || [];

  const { job: activeJob } = useJobProgress(activeJobId, {
    onCompleted: (j) => {
      const doneText =
        j.kind === "localize_extract"
          ? "Đã hoàn tất tách giọng, quét chữ cứng OCR, phân biệt người nói & dịch kịch bản!"
          : "Đã hoàn tất xuất video Việt hóa / Remix!";
      setMsg(doneText);
      toast.success(doneText);
      void load();
    },
    onFailed: (j) => {
      const failText = j.error || "Tác vụ Việt hóa gặp lỗi";
      setErr(failText);
      toast.error(failText);
      void load();
    },
  });

  const activeProj =
    projects.find((p) => p.id === selectedId) || projects[0] || null;

  const runAction = async (id: number, action: "extract" | "render") => {
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ job_id: number | null }>(
        `/api/v1/localize/projects/${id}/${action}`,
        { method: "POST", body: JSON.stringify({ sync: false, tts_provider: "auto" }) }
      );
      if (res.job_id) setActiveJobId(res.job_id);
      const info =
        action === "extract"
          ? `Đã đưa vào hàng đợi tách nhạc MDX-Net, quét chữ cứng & dịch (Tác vụ #${res.job_id}).`
          : `Đã đưa vào hàng đợi xuất video Việt hóa / Remix (Tác vụ #${res.job_id}).`;
      setMsg(info);
      toast.info(info);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể thực thi tác vụ");
    }
  };

  const updateSegField = async (
    proj: LocalizeProject,
    segIdx: number,
    patch: Partial<LocalizeSegment>
  ) => {
    const nextSegs = (proj.segments || []).map((s, idx) =>
      idx === segIdx ? { ...s, ...patch } : s
    );
    await apiFetch(`/api/v1/localize/projects/${proj.id}`, {
      method: "PATCH",
      body: JSON.stringify({ segments: nextSegs }),
    });
    await load();
  };

  const updateSpeakerConfig = async (
    proj: LocalizeProject,
    spkId: string,
    patch: Partial<SpeakerEntry>
  ) => {
    const curSpeakers = { ...(proj.speaker_config?.speakers || {}) };
    curSpeakers[spkId] = {
      ...(curSpeakers[spkId] || {
        label: spkId,
        provider: "edge",
        voice_id: "vi-VN-HoaiMyNeural",
      }),
      ...patch,
    };
    await apiFetch(`/api/v1/localize/projects/${proj.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        speaker_config: { ...(proj.speaker_config || {}), speakers: curSpeakers },
      }),
    });
    await load();
  };

  const updateHardsubBox = async (
    proj: LocalizeProject,
    key: "x" | "y" | "w" | "h",
    value: number
  ) => {
    const nextBox = {
      ...(proj.hardsub_box || { x: 0.06, y: 0.74, w: 0.88, h: 0.16 }),
      [key]: value,
    };
    await apiFetch(`/api/v1/localize/projects/${proj.id}`, {
      method: "PATCH",
      body: JSON.stringify({ hardsub_box: nextBox }),
    });
    await load();
  };

  const handlePreviewLine = async (proj: LocalizeProject, segIdx: number) => {
    const key = `${proj.id}:${segIdx}`;
    setPreviewLoadingKey(key);
    setErr("");
    try {
      const res = await apiFetch<{ audio_url: string }>(
        `/api/v1/localize/projects/${proj.id}/preview-segment`,
        {
          method: "POST",
          body: JSON.stringify({ segment_index: segIdx, tts_provider: "auto" }),
        }
      );
      setPreviewAudioMap((prev) => ({
        ...prev,
        [key]: `${res.audio_url}?t=${Date.now()}`,
      }));
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo âm thanh nghe thử");
    } finally {
      setPreviewLoadingKey(null);
    }
  };

  const toggleCloneVoice = async (proj: LocalizeProject, wantEnable: boolean) => {
    if (!wantEnable) {
      await apiFetch(`/api/v1/localize/projects/${proj.id}`, {
        method: "PATCH",
        body: JSON.stringify({ clone_source_voice: false }),
      });
      await load();
      return;
    }
    setCloneModalOpen(true);
  };

  const confirmEnableClone = async () => {
    if (!activeProj) return;
    setErr("");
    try {
      await apiFetch(`/api/v1/localize/projects/${activeProj.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          clone_source_voice: true,
          clone_consent_confirmed: true,
        }),
      });
      setCloneModalOpen(false);
      const okMsg =
        "Đã bật nhân bản giọng người nói gốc (VieNeu-TTS v3 Nano, phạm vi nội bộ dự án).";
      setMsg(okMsg);
      toast.success(okMsg);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể bật nhân bản giọng");
      setCloneModalOpen(false);
    }
  };

  return {
    activeWorkspaceId,
    wsPolicy,
    canCloneVoice,
    projects,
    shots,
    selectedId,
    setSelectedId,
    activeProj,
    previewAudioMap,
    previewLoadingKey,
    showBoxPreview,
    setShowBoxPreview,
    cloneModalOpen,
    setCloneModalOpen,
    activeJobId,
    setActiveJobId,
    activeJob,
    msg,
    setMsg,
    err,
    setErr,
    load,
    runAction,
    updateSegField,
    updateSpeakerConfig,
    updateHardsubBox,
    handlePreviewLine,
    toggleCloneVoice,
    confirmEnableClone,
  };
}
