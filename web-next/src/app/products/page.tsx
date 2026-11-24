"use client";

import React, { useCallback, useEffect, useState } from "react";
import { FolderKanban, Plus, Trash2 } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";

interface Product {
  id: number;
  workspace_id: number;
  name: string;
  material: string;
  facts: Record<string, string>;
  hidden: number;
}

export default function ProductsPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [products, setProducts] = useState<Product[]>([]);
  const [name, setName] = useState("");
  const [material, setMaterial] = useState("");
  const [stone, setStone] = useState("");
  const [size, setSize] = useState("");
  const [craftsmanship, setCraftsmanship] = useState("");
  const [price, setPrice] = useState("");
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<{ products: Product[] }>(
        `/api/v1/products?workspace_id=${activeWorkspaceId}`
      );
      setProducts(data.products || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải sản phẩm");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    try {
      await apiFetch("/api/v1/products", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          name,
          material,
          facts: { stone, size, craftsmanship, price, notes },
        }),
      });
      setName("");
      setMaterial("");
      setStone("");
      setSize("");
      setCraftsmanship("");
      setPrice("");
      setNotes("");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể thêm sản phẩm");
    }
  };

  const handleDelete = async (id: number) => {
    await apiFetch(`/api/v1/products/${id}`, { method: "DELETE" });
    await load();
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <FolderKanban className="w-6 h-6 text-emerald-400" /> Sản phẩm & Dữ kiện Chuẩn
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Mọi thông số vật liệu, kích thước, giá bán tại đây là nguồn chuẩn để kiểm duyệt lời thoại AI (`BR-PRD-04`).
        </p>
      </div>

      {err && (
        <div className="bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs rounded-lg px-4 py-2.5">
          {err}
        </div>
      )}

      <form
        onSubmit={handleCreate}
        className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-4"
      >
        <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
          <Plus className="w-4 h-4 text-sky-400" /> Thêm Sản Phẩm Mới
        </h2>
        <div className="grid md:grid-cols-2 gap-3 text-xs">
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Tên sản phẩm *"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <input
            value={material}
            onChange={(e) => setMaterial(e.target.value)}
            placeholder="Chất liệu (VD: Bạc S925 nguyên khối)"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <input
            value={stone}
            onChange={(e) => setStone(e.target.value)}
            placeholder="Đá / Chi tiết đính"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <input
            value={size}
            onChange={(e) => setSize(e.target.value)}
            placeholder="Kích thước / Trọng lượng"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <input
            value={craftsmanship}
            onChange={(e) => setCraftsmanship(e.target.value)}
            placeholder="Kỹ thuật chế tác"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <input
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            placeholder="Giá bán niêm yết"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
        </div>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Ghi chú xác thực bổ sung..."
          rows={2}
          className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2 text-xs"
        />
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-xs cursor-pointer"
        >
          Lưu Sản phẩm
        </button>
      </form>

      <div className="grid md:grid-cols-2 gap-4">
        {products.map((p) => (
          <div
            key={p.id}
            className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-2 text-xs"
          >
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-sm font-semibold text-white">{p.name}</h3>
                {p.material && <div className="text-sky-300 mt-0.5">{p.material}</div>}
              </div>
              <button
                onClick={() => void handleDelete(p.id)}
                className="text-slate-400 hover:text-rose-400 cursor-pointer"
                title="Xóa / Ẩn sản phẩm"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-1.5 text-slate-400 pt-1">
              {Object.entries(p.facts || {}).map(
                ([k, v]) =>
                  v && (
                    <div key={k} className="truncate">
                      <span className="text-slate-500">{k}:</span> {v}
                    </div>
                  )
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
