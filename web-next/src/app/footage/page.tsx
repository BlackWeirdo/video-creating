"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Film, Save, Upload } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";

interface FootageItem {
  id: number;
  media_url: string | null;
  duration_s: number;
  width: number;
  height: number;
  orientation: string;
  product_names: string[];
  status: string;
}

interface ShotItem {
  id: number;
  footage_id: number | null;
  start_s: number;
  end_s: number;
  duration_s: number;
  description: string;
  tags: string[];
  has_product: boolean;
  product_names: string[];
  quality: number;
  focus_x: number | null;
  media_url: string | null;
}

export default function FootagePage() {
  const { activeWorkspaceId } = useWorkspace();
  const [footage, setFootage] = useState<FootageItem[]>([]);
  const [shots, setShots] = useState<ShotItem[]>([]);
  const [localPath, setLocalPath] = useState("");
  const [noProduct, setNoProduct] = useState(true);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [focusMap, setFocusMap] = useState<Record<number, number>>({});
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [fRes, sRes] = await Promise.all([
        apiFetch<{ footage: FootageItem[] }>(`/api/v1/footage?workspace_id=${activeWorkspaceId}`),
        apiFetch<{ shots: ShotItem[] }>(`/api/v1/shots?workspace_id=${activeWorkspaceId}`),
      ]);
      setFootage(fRes.footage || []);
      setShots(sRes.shots || []);
      const fm: Record<number, number> = {};
      for (const s of sRes.shots || []) {
        fm[s.id] = s.focus_x ?? 0.5;
      }
      setFocusMap(fm);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải footage/shots");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile) return;
    setErr("");
    setMsg("");
    try {
      const fd = new FormData();
      fd.append("file", uploadFile);
      fd.append("workspace_id", String(activeWorkspaceId));
      fd.append("no_product", noProduct ? "true" : "false");
      fd.append("enqueue_analysis", "true");
      await apiFetch("/api/v1/footage/upload", { method: "POST", body: fd });
      setUploadFile(null);
      setMsg("Đã tải lên footage mới.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Upload thất bại");
    }
  };

  const handleImportLocal = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      await apiFetch("/api/v1/footage/import-local", {
        method: "POST",
        body: JSON.stringify({
          source_path: localPath,
          workspace_id: activeWorkspaceId,
          no_product: noProduct,
          enqueue_analysis: true,
        }),
      });
      setLocalPath("");
      setMsg("Đã nạp file từ máy cục bộ.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Import local thất bại");
    }
  };

  const saveFocus = async (shotId: number) => {
    await apiFetch(`/api/v1/shots/${shotId}`, {
      method: "PATCH",
      body: JSON.stringify({ focus_x: focusMap[shotId] ?? 0.5 }),
    });
    setMsg(`Đã lưu focus_x cho Shot #${shotId}.`);
    await load();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Film className="w-6 h-6 text-sky-400" /> Footage & Kho Shot Cắt Cảnh
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Nạp video quay thô thật của thương hiệu và tinh chỉnh tọa độ tâm `focus_x` khi dựng khung dọc `9:16`.
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

      <div className="grid md:grid-cols-2 gap-4">
        <form
          onSubmit={handleUpload}
          className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3 text-xs"
        >
          <h2 className="font-semibold text-sm text-white flex items-center gap-1.5">
            <Upload className="w-4 h-4 text-sky-400" /> Tải lên Video Quay Thô
          </h2>
          <input
            type="file"
            accept=".mp4,.mov,.mkv,.webm"
            onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
            className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <label className="flex items-center gap-2 text-slate-300">
            <input
              type="checkbox"
              checked={noProduct}
              onChange={(e) => setNoProduct(e.target.checked)}
            />
            Cảnh B-roll / quy trình (không gắn sản phẩm cụ thể)
          </label>
          <button
            type="submit"
            disabled={!uploadFile}
            className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-slate-950 font-semibold cursor-pointer"
          >
            Tải lên & Phân tích Shot
          </button>
        </form>

        <form
          onSubmit={handleImportLocal}
          className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3 text-xs"
        >
          <h2 className="font-semibold text-sm text-white">Nạp Đường Dẫn Cục Bộ</h2>
          <input
            required
            value={localPath}
            onChange={(e) => setLocalPath(e.target.value)}
            placeholder="C:\Videos\clip_san_pham.mp4"
            className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <button
            type="submit"
            className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-sky-300 border border-slate-700 font-medium cursor-pointer"
          >
            Import Local File
          </button>
        </form>
      </div>

      {/* Footage Grid */}
      <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3">
        <h2 className="text-sm font-semibold text-white">
          Danh sách Footage ({footage.length})
        </h2>
        <div className="grid md:grid-cols-3 gap-3 text-xs">
          {footage.map((f) => (
            <div key={f.id} className="bg-[#182235] border border-slate-700/70 rounded-lg p-3 space-y-2">
              {f.media_url && (
                <video
                  src={f.media_url}
                  controls
                  className="w-full h-36 object-cover rounded bg-black"
                />
              )}
              <div className="flex justify-between text-slate-300">
                <span>Footage #{f.id}</span>
                <span>{f.duration_s.toFixed(1)}s • {f.orientation}</span>
              </div>
              <div className="text-[11px] text-slate-400">
                Trạng thái: {f.status} ({f.width}x{f.height})
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Shots Library */}
      <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3">
        <h2 className="text-sm font-semibold text-white">Kho Shot ({shots.length})</h2>
        <div className="grid md:grid-cols-2 gap-3 text-xs">
          {shots.map((s) => (
            <div key={s.id} className="bg-[#182235] border border-slate-700/70 rounded-lg p-3 space-y-2">
              <div className="flex justify-between font-medium text-white">
                <span>
                  Shot #{s.id} ({s.start_s.toFixed(1)}s–{s.end_s.toFixed(1)}s)
                </span>
                <span className="text-amber-300">★ {s.quality}/5</span>
              </div>
              <div className="text-slate-300">{s.description || "Chưa có mô tả"}</div>
              <div className="flex items-center gap-3 pt-1">
                <label className="text-[11px] text-slate-400 shrink-0">
                  Focus X ({(focusMap[s.id] ?? 0.5).toFixed(2)}):
                </label>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={focusMap[s.id] ?? 0.5}
                  onChange={(e) =>
                    setFocusMap((prev) => ({ ...prev, [s.id]: Number(e.target.value) }))
                  }
                  className="flex-1"
                />
                <button
                  type="button"
                  onClick={() => void saveFocus(s.id)}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-sky-500/20 text-sky-300 border border-sky-500/30 cursor-pointer"
                >
                  <Save className="w-3 h-3" /> Lưu
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
