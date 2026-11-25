"use client";

import React, { useState } from "react";
import { UserCheck } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import type {
  AIImageRow,
  ChannelVoiceRow,
  CharacterRow,
} from "@/app/characters/types";
import { CharacterCreatorPanel } from "@/app/characters/_components/CharacterCreatorPanel";
import { ChannelVoiceRecorderCard } from "@/app/characters/_components/ChannelVoiceRecorderCard";
import { CharacterAndImageGallery } from "@/app/characters/_components/CharacterAndImageGallery";
import { PageHeader } from "@/components/vc/PageHeader";
import { PolicyBadge } from "@/components/vc/PolicyBadge";

interface CharactersPageBundle {
  characters: CharacterRow[];
  images: AIImageRow[];
  channelVoices: ChannelVoiceRow[];
}

export default function CharactersPage() {
  const { activeWorkspaceId, activeWorkspace } = useWorkspace();
  const [msg, setMsg] = useState("");

  const { data, error: err, setError: setErr, reload: load } =
    useApiQuery<CharactersPageBundle>(
      async (signal) => {
        const [cRes, iRes, cvRes] = await Promise.all([
          apiFetch<{ characters: CharacterRow[] }>(
            `/api/v1/characters?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
          apiFetch<{ images: AIImageRow[] }>(
            `/api/v1/images?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
          apiFetch<{ channel_voices: ChannelVoiceRow[] }>(
            `/api/v1/channel-voices?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
        ]);
        return {
          characters: cRes.characters || [],
          images: iRes.images || [],
          channelVoices: cvRes.channel_voices || [],
        };
      },
      [activeWorkspaceId],
      { fallbackError: "Lỗi tải Studio Nhân vật" }
    );

  const characters = data?.characters || [];
  const images = data?.images || [];
  const channelVoices = data?.channelVoices || [];

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        icon={<UserCheck className="w-5 h-5" />}
        title="Nhân vật Cố định, Giọng Kênh MC & Ảnh AI"
        badges={<PolicyBadge policy={activeWorkspace?.content_policy} showDetail />}
        description="Quản lý nhân vật cố định Seed, tách nền trong suốt bằng Rembg U2Net, lưu mẫu Giọng Kênh MC 5–10 giây có xác nhận đồng ý và tạo cảnh B-roll."
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

      <CharacterCreatorPanel
        workspaceId={activeWorkspaceId}
        characters={characters}
        onReload={load}
        onMessage={setMsg}
        onError={setErr}
      />

      <ChannelVoiceRecorderCard
        workspaceId={activeWorkspaceId}
        characters={characters}
        channelVoices={channelVoices}
        onReload={load}
        onMessage={setMsg}
        onError={setErr}
      />

      <CharacterAndImageGallery
        characters={characters}
        images={images}
        onReload={load}
        onMessage={setMsg}
        onError={setErr}
      />
    </div>
  );
}
