"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Image as ImageIcon, Mic, Scissors, Square, Trash2, Upload, UserCheck, Wand2 } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";
import { SimulationBadge } from "@/components/SimulationBadge";

interface CharacterRow {
  id: number;
  name: string;
  appearance_prompt: string;
  seed: number;
  voice_id: string;
  ref_image_path: string;
  cutout_image_path: string;
  cutout_simulation_flags?: string[];
}

interface AIImageRow {
  id: number;
  character_id: number | null;
  prompt: string;
  seed: number;
  aspect_ratio: string;
  is_product_shot: boolean;
  image_path: string;
  cutout_path: string;
  motion_shot_id: number | null;
  simulation_flags?: string[];
}

interface ChannelVoiceRow {
  id: number;
  name: string;
  speaker_name: string;
  character_id: number | null;
  duration_s: number;
  audio_url: string;
  voice_token: string;
}

export default function CharactersPage() {
  const { activeWorkspaceId, activeWorkspace } = useWorkspace();
  const [characters, setCharacters] = useState<CharacterRow[]>([]);
  const [images, setImages] = useState<AIImageRow[]>([]);
  const [channelVoices, setChannelVoices] = useState<ChannelVoiceRow[]>([]);

  const [charName, setCharName] = useState("");
  const [appearance, setAppearance] = useState("");
  const [seedInput, setSeedInput] = useState("778899");

  const [imgCharId, setImgCharId] = useState<number>(0);
  const [imgPrompt, setImgPrompt] = useState("");
  const [isProductShot, setIsProductShot] = useState(false);

  // Channel Voice (MC consented 5-10s sample) state
  const [cvName, setCvName] = useState("");
  const [cvSpeaker, setCvSpeaker] = useState("");
  const [cvCharId, setCvCharId] = useState<number>(0);
  const [cvConsent, setCvConsent] = useState(false);
  const [cvFile, setCvFile] = useState<File | null>(null);
  const [recording, setRecording] = useState(false);
  const mediaRecRef = useRef<MediaRecorder | null>(null);
  const recChunksRef = useRef<BlobPart[]>([]);

  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [cRes, iRes, cvRes] = await Promise.all([
        apiFetch<{ characters: CharacterRow[] }>(
          `/api/v1/characters?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ images: AIImageRow[] }>(`/api/v1/images?workspace_id=${activeWorkspaceId}`),
        apiFetch<{ channel_voices: ChannelVoiceRow[] }>(
          `/api/v1/channel-voices?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      setCharacters(cRes.characters || []);
      setImages(iRes.images || []);
      setChannelVoices(cvRes.channel_voices || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Studio Nhân vật");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const startMicRecord = async () => {
    setErr("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recChunksRef.current = [];
      const mr = new MediaRecorder(stream);
      mr.ondataavailable = (ev) => {
        if (ev.data.size > 0) recChunksRef.current.push(ev.data);
      };
      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(recChunksRef.current, { type: "audio/webm" });
        setCvFile(new File([blob], "mc_recorded.webm", { type: "audio/webm" }));
        setMsg("Đã thu xong mẫu giọng! Hãy kiểm tra xác nhận đồng ý rồi bấm Lưu Giọng Kênh.");
      };
      mediaRecRef.current = mr;
      mr.start();
      setRecording(true);
    } catch {
      setErr("Không truy cập được Microphone — bạn có thể chọn file âm thanh mẫu (.wav/.mp3).");
    }
  };

  const stopMicRecord = () => {
    if (mediaRecRef.current && mediaRecRef.current.state !== "inactive") {
      mediaRecRef.current.stop();
    }
    setRecording(false);
  };

  const saveChannelVoice = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    if (!cvFile) {
      setErr("Hãy thu âm bằng Mic (5–10 giây) hoặc chọn file âm thanh mẫu trước.");
      return;
    }
    try {
      const fd = new FormData();
      fd.append("file", cvFile);
      fd.append("name", cvName);
      fd.append("speaker_name", cvSpeaker);
      fd.append("consent_confirmed", cvConsent ? "true" : "false");
      fd.append("workspace_id", String(activeWorkspaceId));
      if (cvCharId > 0) fd.append("character_id", String(cvCharId));

      await apiFetch("/api/v1/channel-voices", { method: "POST", body: fd });
      setCvName("");
      setCvSpeaker("");
      setCvConsent(false);
      setCvFile(null);
      setMsg("Đã lưu Giọng Kênh MC (VieNeu-TTS CPU) cho Workspace!");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể lưu Giọng kênh");
    }
  };

  const createChar = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      await apiFetch("/api/v1/characters", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          name: charName,
          appearance_prompt: appearance,
          seed: Number(seedInput) || undefined,
        }),
      });
      setCharName("");
      setAppearance("");
      setMsg("Đã tạo Nhân vật Cố định mới.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi tạo nhân vật");
    }
  };

  const uploadCharRef = async (charId: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch(`/api/v1/characters/${charId}/upload-ref`, {
      method: "POST",
      body: fd,
    });
    if (!resp.ok) {
      const d = await resp.json();
      setErr(d.detail || "Lỗi upload ảnh tham chiếu");
      return;
    }
    setMsg(`Đã cập nhật ảnh tham chiếu cho Nhân vật #${charId}.`);
    await load();
  };

  const generateImg = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      await apiFetch("/api/v1/images", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          character_id: imgCharId > 0 ? imgCharId : null,
          prompt: imgPrompt,
          is_product_shot: isProductShot,
          animate_to_shot: true,
        }),
      });
      setImgPrompt("");
      setMsg("Đã sinh ảnh AI + chuyển thành shot chuyển động zoompan.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể sinh ảnh AI");
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <UserCheck className="w-6 h-6 text-cyan-400" /> Nhân vật Cố định, Giọng Kênh MC &amp; AI Image Studio
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Khóa Seed đồng nhất, tách nền Rembg U2Net thật, lưu Giọng Kênh 5–10s của MC công ty &amp; tạo Motion Shot (`BR-PRD-01`: Workspace{" "}
          <strong className="text-sky-300">{activeWorkspace?.content_policy || "strict_footage"}</strong> cấm tạo ảnh sản phẩm AI).
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

      <div className="grid md:grid-cols-2 gap-4 text-xs">
        <form
          onSubmit={createChar}
          className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3"
        >
          <h2 className="text-sm font-semibold text-white">Tạo Nhân vật Đồng nhất</h2>
          <input
            required
            value={charName}
            onChange={(e) => setCharName(e.target.value)}
            placeholder="Tên nhân vật (VD: MC Bảo Ngọc)"
            className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <textarea
            rows={2}
            value={appearance}
            onChange={(e) => setAppearance(e.target.value)}
            placeholder="Mô tả ngoại hình cố định (trang phục, tóc, bối cảnh...)"
            className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <input
            type="number"
            value={seedInput}
            onChange={(e) => setSeedInput(e.target.value)}
            placeholder="Seed cố định"
            className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <button
            type="submit"
            className="px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold cursor-pointer"
          >
            Tạo Nhân Vật
          </button>
        </form>

        <form
          onSubmit={generateImg}
          className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3"
        >
          <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
            <Wand2 className="w-4 h-4 text-purple-400" /> Sinh Ảnh Cảnh &amp; Motion Shot
          </h2>
          <select
            value={imgCharId}
            onChange={(e) => setImgCharId(Number(e.target.value))}
            className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value={0}>Không gắn nhân vật</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} (Seed {c.seed})
              </option>
            ))}
          </select>
          <textarea
            required
            rows={2}
            value={imgPrompt}
            onChange={(e) => setImgPrompt(e.target.value)}
            placeholder="Mô tả bối cảnh cảnh quay..."
            className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <label className="flex items-center gap-2 text-slate-300">
            <input
              type="checkbox"
              checked={isProductShot}
              onChange={(e) => setIsProductShot(e.target.checked)}
            />
            Ảnh có sản phẩm (chỉ được bật ở Hybrid / Full AI)
          </label>
          <button
            type="submit"
            className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
          >
            Sinh Ảnh + Shot Chuyển Động
          </button>
        </form>
      </div>

      {/* Consented Channel Voice (5-10s MC Voice Sample for VieNeu-TTS) */}
      <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-4 text-xs">
        <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
          <Mic className="w-4 h-4 text-emerald-400" /> Thư viện Giọng Kênh MC (Thu mẫu 5–10 giây • VieNeu CPU)
        </h2>
        <form onSubmit={saveChannelVoice} className="grid md:grid-cols-4 gap-3 items-end">
          <input
            required
            value={cvName}
            onChange={(e) => setCvName(e.target.value)}
            placeholder="Tên giọng (VD: Giọng Kênh Bảo Ngọc)"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <input
            required
            value={cvSpeaker}
            onChange={(e) => setCvSpeaker(e.target.value)}
            placeholder="Họ tên MC / Chủ giọng đồng ý"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <select
            value={cvCharId}
            onChange={(e) => setCvCharId(Number(e.target.value))}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value={0}>Dùng chung toàn Workspace</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>
                Gắn mặc định cho: {c.name}
              </option>
            ))}
          </select>
          <div className="flex gap-2">
            {!recording ? (
              <button
                type="button"
                onClick={() => void startMicRecord()}
                className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 font-semibold cursor-pointer"
              >
                <Mic className="w-3.5 h-3.5" /> Thu Mic
              </button>
            ) : (
              <button
                type="button"
                onClick={stopMicRecord}
                className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-rose-500 text-white font-semibold cursor-pointer animate-pulse"
              >
                <Square className="w-3.5 h-3.5" /> Dừng thu
              </button>
            )}
            <label className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-[#182235] border border-slate-700 text-sky-300 cursor-pointer">
              <Upload className="w-3.5 h-3.5" /> File mẫu
              <input
                type="file"
                accept=".wav,.mp3,.m4a,.webm,.ogg"
                className="hidden"
                onChange={(e) => setCvFile(e.target.files?.[0] || null)}
              />
            </label>
          </div>
          <label className="md:col-span-3 flex items-center gap-2 text-slate-300">
            <input
              type="checkbox"
              checked={cvConsent}
              onChange={(e) => setCvConsent(e.target.checked)}
            />
            Xác nhận MC / chủ giọng thuộc công ty và đã đồng ý cho phép nhân bản giọng phục vụ kênh này.
            {cvFile && <span className="text-emerald-300 ml-1">({cvFile.name})</span>}
          </label>
          <button
            type="submit"
            className="px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold cursor-pointer"
          >
            Lưu Giọng Kênh
          </button>
        </form>

        {channelVoices.length > 0 && (
          <div className="grid md:grid-cols-2 gap-2.5 pt-1">
            {channelVoices.map((cv) => (
              <div
                key={cv.id}
                className="bg-[#182235] border border-slate-800 rounded-lg p-3 flex flex-col gap-1.5"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-semibold text-white">{cv.name}</span>{" "}
                    <span className="text-slate-400">({cv.speaker_name} • {cv.duration_s}s)</span>
                  </div>
                  <button
                    type="button"
                    onClick={async () => {
                      await apiFetch(`/api/v1/channel-voices/${cv.id}`, { method: "DELETE" });
                      await load();
                    }}
                    className="text-slate-400 hover:text-rose-400 cursor-pointer"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
                {cv.audio_url && <audio controls src={cv.audio_url} className="h-7 w-full" />}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="grid md:grid-cols-2 gap-4 text-xs">
        <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-2.5">
          <h3 className="font-semibold text-white">Nhân vật ({characters.length})</h3>
          {characters.map((c) => (
            <div key={c.id} className="bg-[#182235] border border-slate-800 rounded-lg p-3 space-y-2">
              <div className="flex justify-between font-semibold text-white">
                <span>{c.name}</span>
                <span className="text-cyan-300">Seed {c.seed} • {c.voice_id}</span>
              </div>
              <div className="text-slate-400">{c.appearance_prompt || "—"}</div>
              <div className="flex flex-wrap gap-2 items-center">
                <label className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-sky-300 cursor-pointer">
                  <Upload className="w-3 h-3 inline mr-1" /> Upload Ref
                  <input
                    type="file"
                    accept=".png,.jpg,.jpeg,.webp"
                    className="hidden"
                    onChange={(ev) => {
                      const f = ev.target.files?.[0];
                      if (f) void uploadCharRef(c.id, f);
                    }}
                  />
                </label>
                {c.ref_image_path && (
                  <button
                    type="button"
                    onClick={async () => {
                      await apiFetch(`/api/v1/characters/${c.id}/cutout`, { method: "POST" });
                      setMsg(`Đã tách nền PNG (Rembg U2Net) cho nhân vật #${c.id}.`);
                      await load();
                    }}
                    className="px-2 py-1 rounded bg-purple-500/20 text-purple-300 cursor-pointer"
                  >
                    <Scissors className="w-3 h-3 inline mr-1" /> Tách nền PNG
                  </button>
                )}
              </div>
              <SimulationBadge flags={c.cutout_simulation_flags} />
            </div>
          ))}
        </div>

        <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-2.5">
          <h3 className="font-semibold text-white flex items-center gap-1.5">
            <ImageIcon className="w-4 h-4 text-sky-400" /> Kho Ảnh AI ({images.length})
          </h3>
          <div className="grid sm:grid-cols-2 gap-2.5">
            {images.map((im) => (
              <div key={im.id} className="bg-[#182235] border border-slate-800 rounded-lg p-2.5 space-y-1.5">
                {im.image_path && (
                  <img
                    src={`/files/${im.image_path}`}
                    alt={im.prompt}
                    className="w-full h-36 object-cover rounded bg-black"
                  />
                )}
                <div className="text-[11px] text-slate-300 line-clamp-2">{im.prompt}</div>
                <div className="text-[10px] text-slate-400">
                  Seed {im.seed} • Shot: {im.motion_shot_id ?? "chưa tạo"}
                </div>
                <SimulationBadge flags={im.simulation_flags} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
