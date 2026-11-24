"use client";

import React, { useCallback, useEffect, useState } from "react";
import { BookOpen, Play, Plus, RefreshCw } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";
import { SimulationBadge } from "@/components/SimulationBadge";

interface NovelChapter {
  id: number;
  chapter_index: number;
  title: string;
  word_count: number;
  status: string;
  video_id: number | null;
  output_path: string;
  video_url: string;
}

interface NovelProject {
  id: number;
  title: string;
  aspect_ratio: string;
  style_preset: string;
  voice_id?: string;
  status: string;
  total_chapters: number;
  ready_chapters: number;
  chapters: NovelChapter[];
  simulation_flags?: string[];
}

interface CharacterOption {
  id: number;
  name: string;
  voice_id: string;
}

interface ChannelVoiceOption {
  id: number;
  name: string;
  speaker_name: string;
  voice_token: string;
}

const BASE_NOVEL_VOICES = [
  { value: "vi-VN-HoaiMyNeural", label: "Edge TTS: Hoài My (Nữ)" },
  { value: "vi-VN-NamMinhNeural", label: "Edge TTS: Nam Minh (Nam)" },
  { value: "vieneu:Mỹ Duyên", label: "VieNeu CPU: Mỹ Duyên (Nữ đọc truyện)" },
  { value: "vieneu:Đức Trí", label: "VieNeu CPU: Đức Trí (Nam đọc truyện)" },
  { value: "vieneu:Anh Khôi", label: "VieNeu CPU: Anh Khôi (Nam kể chuyện)" },
  { value: "vieneu:Trúc Ly", label: "VieNeu CPU: Trúc Ly (Nữ tự nhiên)" },
];

export default function NovelStudioPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [projects, setProjects] = useState<NovelProject[]>([]);
  const [characters, setCharacters] = useState<CharacterOption[]>([]);
  const [channelVoices, setChannelVoices] = useState<ChannelVoiceOption[]>([]);

  const [title, setTitle] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [aspectRatio, setAspectRatio] = useState("9:16");
  const [characterId, setCharacterId] = useState<number>(0);
  const [voiceId, setVoiceId] = useState("vi-VN-HoaiMyNeural");
  const [previewChapters, setPreviewChapters] = useState<
    Array<{ chapter_index: number; title: string; word_count: number }>
  >([]);
  const [renderingId, setRenderingId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [res, cRes, cvRes] = await Promise.all([
        apiFetch<{ projects: NovelProject[] }>(
          `/api/v1/novels/projects?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ characters: CharacterOption[] }>(
          `/api/v1/characters?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ channel_voices: ChannelVoiceOption[] }>(
          `/api/v1/channel-voices?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      setProjects(res.projects || []);
      setCharacters(cRes.characters || []);
      setChannelVoices(cvRes.channel_voices || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Studio Tiểu thuyết");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const voiceChoices = [
    ...channelVoices.map((cv) => ({
      value: cv.voice_token,
      label: `Giọng Kênh: ${cv.name} (${cv.speaker_name})`,
    })),
    ...BASE_NOVEL_VOICES,
  ];

  const previewSplit = async () => {
    if (!sourceText.trim()) return;
    const res = await apiFetch<{
      chapters: Array<{ chapter_index: number; title: string; word_count: number }>;
    }>("/api/v1/novels/split-preview", {
      method: "POST",
      body: JSON.stringify({ source_text: sourceText, target_words_per_chapter: 140 }),
    });
    setPreviewChapters(res.chapters || []);
  };

  const createNovel = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ project: NovelProject }>("/api/v1/novels/projects", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          title,
          source_text: sourceText,
          aspect_ratio: aspectRatio,
          character_id: characterId > 0 ? characterId : null,
          voice_id: voiceId,
        }),
      });
      setTitle("");
      setSourceText("");
      setPreviewChapters([]);
      setMsg(`Đã tạo truyện #${res.project.id} với ${res.project.total_chapters} chương.`);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo dự án Tiểu thuyết");
    }
  };

  const renderProject = async (pid: number, force = false) => {
    setRenderingId(pid);
    setErr("");
    setMsg("");
    try {
      await apiFetch(`/api/v1/novels/projects/${pid}/render`, {
        method: "POST",
        body: JSON.stringify({ sync: true, force }),
      });
      setMsg(`Đã render xong các chương cho dự án #${pid}.`);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi render chương tiểu thuyết");
    } finally {
      setRenderingId(null);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <BookOpen className="w-6 h-6 text-emerald-400" /> Studio Tiểu thuyết Đa chương → Video
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Tự động tách chương, đọc truyện bằng giọng thật Edge TTS / VieNeu CPU / Giọng Kênh MC và phục hồi từ đúng chương còn thiếu.
        </p>
      </div>

      {msg && (
        <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs rounded-lg px-4 py-2.5">
          {msg}
        </div>
      )}
      {err && (
        <div className="bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs rounded-lg px-4 py-2.5">
          {err}
        </div>
      )}

      <form
        onSubmit={createNovel}
        className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs"
      >
        <div className="grid md:grid-cols-4 gap-3">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Tên bộ truyện / tiểu thuyết"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2 md:col-span-2"
          />
          <select
            value={voiceId}
            onChange={(e) => setVoiceId(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            {voiceChoices.map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </select>
          <select
            value={aspectRatio}
            onChange={(e) => setAspectRatio(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="9:16">9:16 Reels / Shorts</option>
            <option value="16:9">16:9 YouTube Ngang</option>
            <option value="1:1">1:1 Vuông</option>
          </select>
        </div>
        <div className="grid md:grid-cols-2 gap-3">
          <select
            value={characterId}
            onChange={(e) => setCharacterId(Number(e.target.value))}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value={0}>Không gắn nhân vật dẫn truyện</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>
                Nhân vật: {c.name} ({c.voice_id})
              </option>
            ))}
          </select>
        </div>
        <textarea
          required
          rows={5}
          value={sourceText}
          onChange={(e) => setSourceText(e.target.value)}
          placeholder={"Chương 1: Mở đầu\nNội dung chương một...\n\nChương 2: Bước ngoặt\nNội dung chương hai..."}
          className="w-full bg-[#182235] border border-slate-700 rounded-lg p-3"
        />
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void previewSplit()}
            className="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 cursor-pointer"
          >
            Xem trước tách chương ({previewChapters.length})
          </button>
          <button
            type="submit"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold cursor-pointer"
          >
            <Plus className="w-4 h-4" /> Tạo Dự án Tiểu thuyết
          </button>
        </div>
        {previewChapters.length > 0 && (
          <div className="grid md:grid-cols-3 gap-2 pt-2">
            {previewChapters.map((c) => (
              <div
                key={c.chapter_index}
                className="bg-[#182235] border border-slate-800 rounded px-3 py-2"
              >
                <div className="font-semibold text-white truncate">{c.title}</div>
                <div className="text-[11px] text-slate-400">{c.word_count} từ</div>
              </div>
            ))}
          </div>
        )}
      </form>

      <div className="space-y-4">
        {projects.map((p) => (
          <div
            key={p.id}
            className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold text-white">
                  #{p.id} — {p.title}
                </h2>
                <div className="text-[11px] text-slate-400">
                  {p.ready_chapters}/{p.total_chapters} chương hoàn tất • {p.aspect_ratio} •{" "}
                  <span className="text-sky-300">{p.status}</span>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={renderingId === p.id}
                  onClick={() => void renderProject(p.id, false)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer disabled:opacity-50"
                >
                  <Play className="w-3.5 h-3.5" />{" "}
                  {renderingId === p.id ? "Đang render..." : "Render tiếp (Checkpoint)"}
                </button>
                <button
                  type="button"
                  disabled={renderingId === p.id}
                  onClick={() => void renderProject(p.id, true)}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-800 text-slate-300 cursor-pointer"
                >
                  <RefreshCw className="w-3.5 h-3.5" /> Render lại tất cả
                </button>
              </div>
            </div>
            <SimulationBadge flags={p.simulation_flags} />
            <div className="grid md:grid-cols-2 gap-3">
              {p.chapters.map((ch) => (
                <div
                  key={ch.id}
                  className="bg-[#182235] border border-slate-800 rounded-lg p-3 space-y-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-white truncate">{ch.title}</span>
                    <span className="text-[11px] text-emerald-300">{ch.status}</span>
                  </div>
                  {ch.video_url && (
                    <video
                      controls
                      preload="metadata"
                      src={ch.video_url}
                      className="w-full max-h-48 rounded bg-black"
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
