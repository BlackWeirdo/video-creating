"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Layers, RefreshCw } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";

interface ProductOption {
  id: number;
  name: string;
  material: string;
}

interface BatchItemRow {
  id: number;
  item_index: number;
  variant_label: string;
  style_preset: string;
  hook_angle: string;
  step: string;
  video_id: number | null;
  video_status: string | null;
  video_quality_score: number | null;
  error: string | null;
}

interface BatchRunRow {
  id: number;
  title: string;
  source_kind: string;
  ab_count: number;
  status: string;
  total_items?: number;
  completed_items?: number;
  failed_items?: number;
  items?: BatchItemRow[];
}

export default function BatchStudioPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [batches, setBatches] = useState<BatchRunRow[]>([]);
  const [activeBatch, setActiveBatch] = useState<BatchRunRow | null>(null);
  const [products, setProducts] = useState<ProductOption[]>([]);

  const [title, setTitle] = useState("");
  const [sourceKind, setSourceKind] = useState<"products" | "prompts" | "trends">("products");
  const [selectedProdIds, setSelectedProdIds] = useState<number[]>([]);
  const [promptsText, setPromptsText] = useState("");
  const [abCount, setAbCount] = useState(2);
  const [styleA, setStyleA] = useState("tiktok_karaoke");
  const [styleB, setStyleB] = useState("box_highlight");

  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [bRes, pRes] = await Promise.all([
        apiFetch<{ batches: BatchRunRow[] }>(`/api/v1/batches?workspace_id=${activeWorkspaceId}`),
        apiFetch<{ products: ProductOption[] }>(`/api/v1/products?workspace_id=${activeWorkspaceId}`),
      ]);
      const list = bRes.batches || [];
      setBatches(list);
      setProducts(pRes.products || []);
      if (list.length > 0) {
        const detail = await apiFetch<{ batch: BatchRunRow }>(`/api/v1/batches/${list[0].id}`);
        setActiveBatch(detail.batch);
      }
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Batch Studio");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const inspectBatch = async (id: number) => {
    const detail = await apiFetch<{ batch: BatchRunRow }>(`/api/v1/batches/${id}`);
    setActiveBatch(detail.batch);
  };

  const createBatch = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const items =
        sourceKind === "products"
          ? selectedProdIds
          : promptsText
              .split(/\r?\n/)
              .map((l) => l.trim())
              .filter(Boolean);
      const res = await apiFetch<{ batch: BatchRunRow; job_id: number }>("/api/v1/batches", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          title: title || `Batch ${sourceKind}`,
          source_kind: sourceKind,
          items,
          ab_count: abCount,
          style_presets: [styleA, styleB],
          sync: false,
        }),
      });
      setTitle("");
      setPromptsText("");
      setMsg(`Đã khởi chạy Batch #${res.batch.id} (Job #${res.job_id}).`);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo Batch");
    }
  };

  const retryFailed = async (id: number) => {
    const res = await apiFetch<{ job_id: number }>(`/api/v1/batches/${id}/retry`, {
      method: "POST",
      body: JSON.stringify({ failed_only: true, sync: false }),
    });
    setMsg(`Đã chạy lại các mục lỗi từ checkpoint của Batch #${id} (Job #${res.job_id}).`);
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Layers className="w-6 h-6 text-indigo-400" /> Batch Studio & Biến thể Sản phẩm A/B
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Sinh hàng loạt video với 1–3 biến thể Hook/Style A-B-C kèm checkpoint phục hồi đúng bước lỗi.
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
        onSubmit={createBatch}
        className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs"
      >
        <div className="grid md:grid-cols-4 gap-3">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Tên chiến dịch Batch"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <select
            value={sourceKind}
            onChange={(e) => setSourceKind(e.target.value as "products" | "prompts" | "trends")}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="products">Theo Sản phẩm Workspace</option>
            <option value="prompts">Theo danh sách Prompt / Ý tưởng</option>
            <option value="trends">Theo Trend ID</option>
          </select>
          <select
            value={abCount}
            onChange={(e) => setAbCount(Number(e.target.value))}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value={1}>1 bản gốc (A)</option>
            <option value={2}>2 biến thể A/B</option>
            <option value={3}>3 biến thể A/B/C</option>
          </select>
          <div className="flex gap-2">
            <select
              value={styleA}
              onChange={(e) => setStyleA(e.target.value)}
              className="bg-[#182235] border border-slate-700 rounded-lg px-2 py-2 flex-1"
            >
              <option value="tiktok_karaoke">Style A: Karaoke</option>
              <option value="box_highlight">Style A: Hộp</option>
              <option value="neon_glow">Style A: Neon</option>
            </select>
            <select
              value={styleB}
              onChange={(e) => setStyleB(e.target.value)}
              className="bg-[#182235] border border-slate-700 rounded-lg px-2 py-2 flex-1"
            >
              <option value="box_highlight">Style B: Hộp</option>
              <option value="neon_glow">Style B: Neon</option>
              <option value="minimal_bottom">Style B: Tối giản</option>
            </select>
          </div>
        </div>

        {sourceKind === "products" ? (
          <div className="flex flex-wrap gap-2">
            {products.map((p) => {
              const checked = selectedProdIds.includes(p.id);
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() =>
                    setSelectedProdIds((prev) =>
                      checked ? prev.filter((x) => x !== p.id) : [...prev, p.id]
                    )
                  }
                  className={`px-3 py-1.5 rounded-lg border cursor-pointer ${
                    checked
                      ? "bg-sky-500/20 border-sky-400 text-sky-300"
                      : "bg-[#182235] border-slate-700 text-slate-300"
                  }`}
                >
                  {p.name} ({p.material || "—"})
                </button>
              );
            })}
          </div>
        ) : (
          <textarea
            rows={3}
            value={promptsText}
            onChange={(e) => setPromptsText(e.target.value)}
            placeholder={
              sourceKind === "prompts"
                ? "Mỗi dòng 1 ý tưởng / prompt video..."
                : "Mỗi dòng 1 Trend ID..."
            }
            className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
        )}

        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
        >
          Chạy Batch & Sinh Biến Thể
        </button>
      </form>

      <div className="grid lg:grid-cols-3 gap-4 text-xs">
        <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-2">
          <h3 className="font-semibold text-white">Lịch sử Batch ({batches.length})</h3>
          {batches.map((b) => (
            <div
              key={b.id}
              onClick={() => void inspectBatch(b.id)}
              className={`p-3 rounded-lg border cursor-pointer space-y-1 ${
                activeBatch?.id === b.id
                  ? "bg-indigo-500/10 border-indigo-400/50"
                  : "bg-[#182235] border-slate-800"
              }`}
            >
              <div className="flex justify-between font-semibold text-white">
                <span>{b.title}</span>
                <span className="text-sky-300">{b.status}</span>
              </div>
              <div className="text-[11px] text-slate-400">
                {b.source_kind} • {b.completed_items ?? 0}/{b.total_items ?? 0} xong
                {b.failed_items ? ` • ${b.failed_items} lỗi` : ""}
              </div>
            </div>
          ))}
        </div>

        <div className="lg:col-span-2 bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-white">
              Biến thể A/B & Checkpoint {activeBatch ? `— #${activeBatch.id}` : ""}
            </h3>
            {activeBatch && (
              <button
                type="button"
                onClick={() => void retryFailed(activeBatch.id)}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-amber-300 cursor-pointer"
              >
                <RefreshCw className="w-3 h-3" /> Thử lại mục lỗi
              </button>
            )}
          </div>
          {!activeBatch?.items?.length ? (
            <div className="text-slate-500 py-6 text-center">Chưa có biến thể nào.</div>
          ) : (
            <div className="grid md:grid-cols-2 gap-2.5">
              {activeBatch.items.map((it) => (
                <div
                  key={it.id}
                  className="bg-[#182235] border border-slate-700/70 rounded-lg p-3 space-y-1"
                >
                  <div className="flex justify-between font-semibold text-white">
                    <span>
                      Item #{it.item_index + 1} • Biến thể {it.variant_label}
                    </span>
                    <span className="text-emerald-300">{it.step}</span>
                  </div>
                  <div className="text-[11px] text-slate-400">
                    Style: {it.style_preset} • Hook: {it.hook_angle}
                  </div>
                  {it.video_quality_score !== null && (
                    <div className="text-[11px] text-amber-300">
                      Điểm QC: {it.video_quality_score.toFixed(1)}
                    </div>
                  )}
                  {it.error && <div className="text-[11px] text-rose-300">{it.error}</div>}
                  {it.video_id && (
                    <Link href={`/videos/${it.video_id}`} className="text-sky-400 hover:underline inline-block pt-1">
                      Mở Video #{it.video_id} →
                    </Link>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
