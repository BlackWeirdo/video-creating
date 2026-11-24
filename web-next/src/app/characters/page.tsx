"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Image as ImageIcon, Scissors, Upload, UserCheck, Wand2 } from "lucide-react";
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

export default function CharactersPage() {
  const { activeWorkspaceId, activeWorkspace } = useWorkspace();
  const [characters, setCharacters] = useState<CharacterRow[]>([]);
  const [images, setImages] = useState<AIImageRow[]>([]);

  const [charName, setCharName] = useState("");
  const [appearance, setAppearance] = useState("");
  const [seedInput, setSeedInput] = useState("778899");

  const [imgCharId, setImgCharId] = useState<number>(0);
  const [imgPrompt, setImgPrompt] = useState("");
  const [isProductShot, setIsProductShot] = useState(false);

  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [cRes, iRes] = await Promise.all([
        apiFetch<{ characters: CharacterRow[] }>(
          `/api/v1/characters?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ images: AIImageRow[] }>(`/api/v1/images?workspace_id=${activeWorkspaceId}`),
      ]);
      setCharacters(cRes.characters || []);
      setImages(iRes.images || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Studio Nhân vật");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

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
          <UserCheck className="w-6 h-6 text-cyan-400" /> Nhân vật Cố định &amp; AI Image Studio
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Khóa Seed + Mô tả ngoại hình đồng nhất qua mọi cảnh, tách nền RGBA PNG &amp; tạo Motion Shot (`BR-PRD-01`: Workspace{" "}
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

      <div className="grid md:grid-cols-2 gap-4 text-xs">
        <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-2.5">
          <h3 className="font-semibold text-white">Nhân vật ({characters.length})</h3>
          {characters.map((c) => (
            <div key={c.id} className="bg-[#182235] border border-slate-800 rounded-lg p-3 space-y-2">
              <div className="flex justify-between font-semibold text-white">
                <span>{c.name}</span>
                <span className="text-cyan-300">Seed {c.seed}</span>
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
                      setMsg(`Đã tách nền PNG cho nhân vật #${c.id}.`);
                      await load();
                    }}
                    className="px-2 py-1 rounded bg-purple-500/20 text-purple-300 cursor-pointer"
                  >
                    <Scissors className="w-3 h-3 inline mr-1" /> Tách nền PNG
                  </button>
                )}
              </div>
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
