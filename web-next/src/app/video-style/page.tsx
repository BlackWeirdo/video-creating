"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Music, Palette, Plus, Trash2 } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";

interface StylePreset {
  id: string;
  name: string;
  subtitle_style: string;
  font_size: number;
  highlight_color: string;
  position: string;
  ducking_enabled: boolean;
  music_volume: number;
  intro_text: string;
  outro_text: string;
  is_builtin: boolean;
}

interface AudioAsset {
  id: number;
  kind: string;
  title: string;
  duration_s: number;
  media_url: string | null;
}

export default function VideoStylePage() {
  const { activeWorkspaceId } = useWorkspace();
  const [styles, setStyles] = useState<StylePreset[]>([]);
  const [assets, setAssets] = useState<AudioAsset[]>([]);
  const [name, setName] = useState("");
  const [subStyle, setSubStyle] = useState("karaoke_highlight");
  const [highlightColor, setHighlightColor] = useState("#FFE082");
  const [introText, setIntroText] = useState("");
  const [outroText, setOutroText] = useState("");
  const [ducking, setDucking] = useState(true);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioKind, setAudioKind] = useState<"music" | "sfx">("music");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [sRes, aRes] = await Promise.all([
        apiFetch<{ styles: StylePreset[] }>(`/api/v1/styles?workspace_id=${activeWorkspaceId}`),
        apiFetch<{ assets: AudioAsset[] }>(`/api/v1/assets?workspace_id=${activeWorkspaceId}`),
      ]);
      setStyles(sRes.styles || []);
      setAssets(aRes.assets || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Style/Audio");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreateStyle = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    try {
      await apiFetch("/api/v1/styles", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          name,
          subtitle_style: subStyle,
          highlight_color: highlightColor,
          intro_text: introText,
          outro_text: outroText,
          ducking_enabled: ducking,
        }),
      });
      setName("");
      setIntroText("");
      setOutroText("");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo Style");
    }
  };

  const handleDeleteStyle = async (id: string) => {
    await apiFetch(`/api/v1/styles/${id}`, { method: "DELETE" });
    await load();
  };

  const handleUploadAsset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!audioFile) return;
    const fd = new FormData();
    fd.append("file", audioFile);
    fd.append("workspace_id", String(activeWorkspaceId));
    fd.append("kind", audioKind);
    await apiFetch("/api/v1/assets/upload", { method: "POST", body: fd });
    setAudioFile(null);
    await load();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Palette className="w-6 h-6 text-purple-400" /> Video Style Engine & Nhạc/SFX
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          6 kiểu phụ đề ASS nhảy chữ, Auto-Ducking nhạc nền `sidechaincompress` và chuẩn hóa `-14 LUFS`.
        </p>
      </div>

      {err && (
        <div className="bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs rounded-lg px-4 py-2.5">
          {err}
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        <form
          onSubmit={handleCreateStyle}
          className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs"
        >
          <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
            <Plus className="w-4 h-4 text-sky-400" /> Tạo Style Preset Mới
          </h2>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Tên preset (VD: Review Nhanh S925)"
            className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <div className="grid grid-cols-2 gap-3">
            <select
              value={subStyle}
              onChange={(e) => setSubStyle(e.target.value)}
              className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            >
              <option value="karaoke_highlight">Karaoke Highlight (\kf)</option>
              <option value="tiktok_pop">TikTok Pop Nảy Chữ</option>
              <option value="box_highlight">Hộp Nền Đậm</option>
              <option value="neon_glow">Neon Glow Hai Lớp</option>
              <option value="minimal_bottom">Tối Giản Tinh Tế</option>
              <option value="bilingual">Song Ngữ Việt - Anh</option>
            </select>
            <input
              type="text"
              value={highlightColor}
              onChange={(e) => setHighlightColor(e.target.value)}
              placeholder="#FFE082"
              className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <input
              value={introText}
              onChange={(e) => setIntroText(e.target.value)}
              placeholder="Chữ Intro mở đầu (tuỳ chọn)"
              className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            />
            <input
              value={outroText}
              onChange={(e) => setOutroText(e.target.value)}
              placeholder="Chữ Outro kết thúc (tuỳ chọn)"
              className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            />
          </div>
          <label className="flex items-center gap-2 text-slate-300">
            <input
              type="checkbox"
              checked={ducking}
              onChange={(e) => setDucking(e.target.checked)}
            />
            Bật Auto-Ducking nhạc nền khi có giọng đọc
          </label>
          <button
            type="submit"
            className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
          >
            Lưu Style Preset
          </button>
        </form>

        <form
          onSubmit={handleUploadAsset}
          className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs"
        >
          <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
            <Music className="w-4 h-4 text-emerald-400" /> Nạp Nhạc nền & SFX ({assets.length})
          </h2>
          <div className="flex gap-2">
            <select
              value={audioKind}
              onChange={(e) => setAudioKind(e.target.value as "music" | "sfx")}
              className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            >
              <option value="music">Nhạc nền (BGM)</option>
              <option value="sfx">Hiệu ứng (SFX)</option>
            </select>
            <input
              type="file"
              accept=".mp3,.wav,.m4a,.aac,.ogg,.flac"
              onChange={(e) => setAudioFile(e.target.files?.[0] || null)}
              className="flex-1 bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            />
            <button
              type="submit"
              disabled={!audioFile}
              className="px-3.5 py-2 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 cursor-pointer"
            >
              Tải lên
            </button>
          </div>
          <div className="space-y-1.5 max-h-40 overflow-y-auto pt-1">
            {assets.map((a) => (
              <div
                key={a.id}
                className="flex items-center justify-between bg-[#182235] rounded px-3 py-1.5"
              >
                <span>
                  <strong className="text-sky-300 uppercase">{a.kind}</strong> • {a.title} (
                  {a.duration_s.toFixed(1)}s)
                </span>
                {a.media_url && <audio controls src={a.media_url} className="h-7 w-40" />}
              </div>
            ))}
          </div>
        </form>
      </div>

      <div className="grid md:grid-cols-3 gap-4 text-xs">
        {styles.map((s) => (
          <div
            key={s.id}
            className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-2"
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-white">{s.name}</span>
              {!s.is_builtin ? (
                <button
                  onClick={() => void handleDeleteStyle(s.id)}
                  className="text-slate-400 hover:text-rose-400 cursor-pointer"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              ) : (
                <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-400">
                  Mặc định
                </span>
              )}
            </div>
            <div className="text-slate-400">
              Kiểu chữ: <span className="text-sky-300">{s.subtitle_style}</span>
            </div>
            <div className="flex items-center gap-2 text-slate-400">
              <span>Màu nhấn:</span>
              <span
                className="inline-block w-3.5 h-3.5 rounded-full border border-white/30"
                style={{ backgroundColor: s.highlight_color }}
              />
              <span>{s.highlight_color}</span>
              <span>• Ducking: {s.ducking_enabled ? "Bật" : "Tắt"}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
