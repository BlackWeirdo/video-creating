"use client";

import React, { useCallback, useEffect, useState } from "react";
import { FolderKanban, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { PageHeader } from "@/components/vc/PageHeader";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, TextareaBox, TextInput } from "@/components/ui/form-controls";
import { ModalDialog } from "@/components/ui/overlays";

interface Product {
  id: number;
  workspace_id: number;
  name: string;
  material: string;
  facts: Record<string, string>;
  hidden: number;
}

const FACT_LABELS: Record<string, string> = {
  stone: "Đá / Chi tiết",
  size: "Kích thước",
  craftsmanship: "Chế tác",
  price: "Giá bán",
  notes: "Ghi chú",
};

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
  const [deleteTarget, setDeleteTarget] = useState<Product | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<{ products: Product[] }>(
        `/api/v1/products?workspace_id=${activeWorkspaceId}`
      );
      setProducts(data.products || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải danh mục sản phẩm");
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
      toast.success("Đã lưu sản phẩm & bộ dữ kiện chuẩn.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể thêm sản phẩm");
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    await apiFetch(`/api/v1/products/${deleteTarget.id}`, { method: "DELETE" });
    toast.success(`Đã ẩn sản phẩm "${deleteTarget.name}".`);
    setDeleteTarget(null);
    await load();
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <PageHeader
        icon={<FolderKanban className="w-5 h-5" />}
        title="Sản phẩm & Bộ Dữ Kiện Xác Thực"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {products.length} sản phẩm
          </Badge>
        }
        description="Mọi thông số chất liệu, kích thước và giá niêm yết tại đây là nguồn sự thật duy nhất để AI đối chiếu lời thoại, ngăn bịa đặt thông tin."
      />

      {err && (
        <div
          role="alert"
          className="rounded-[11px] border border-[var(--st-rose-bd)] bg-[var(--st-rose-bg)] px-4 py-2.5 text-[13px] text-[var(--st-rose-tx)]"
        >
          {err}
        </div>
      )}

      <Card tinted>
        <form onSubmit={handleCreate} className="space-y-4">
          <SectionHeading>
            <Plus className="w-4 h-4 text-[var(--c-icon)]" /> Thêm Sản Phẩm Mới
          </SectionHeading>

          <div className="grid md:grid-cols-2 gap-3.5">
            <div>
              <FieldLabel htmlFor="prd-name">Tên sản phẩm *</FieldLabel>
              <TextInput
                id="prd-name"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="VD: Dây chuyền Bạc Hồ Điệp S925"
              />
            </div>
            <div>
              <FieldLabel htmlFor="prd-mat">Chất liệu chính</FieldLabel>
              <TextInput
                id="prd-mat"
                value={material}
                onChange={(e) => setMaterial(e.target.value)}
                placeholder="VD: Bạc S925 nguyên khối phủ bạch kim"
              />
            </div>
            <div>
              <FieldLabel htmlFor="prd-stone">Đá / Chi tiết đính kèm</FieldLabel>
              <TextInput
                id="prd-stone"
                value={stone}
                onChange={(e) => setStone(e.target.value)}
                placeholder="VD: Đá CZ 5A giác cắt kim cương"
              />
            </div>
            <div>
              <FieldLabel htmlFor="prd-size">Kích thước / Trọng lượng</FieldLabel>
              <TextInput
                id="prd-size"
                value={size}
                onChange={(e) => setSize(e.target.value)}
                placeholder="VD: Dây 40+5cm • 3.8g"
              />
            </div>
            <div>
              <FieldLabel htmlFor="prd-craft">Kỹ thuật chế tác</FieldLabel>
              <TextInput
                id="prd-craft"
                value={craftsmanship}
                onChange={(e) => setCraftsmanship(e.target.value)}
                placeholder="VD: Đánh bóng gương thủ công"
              />
            </div>
            <div>
              <FieldLabel htmlFor="prd-price">Giá bán niêm yết</FieldLabel>
              <TextInput
                id="prd-price"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="VD: 389.000đ"
              />
            </div>
          </div>

          <div>
            <FieldLabel htmlFor="prd-notes">
              Ghi chú bảo hành &amp; cam kết được phép nhắc trong video
            </FieldLabel>
            <TextareaBox
              id="prd-notes"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="VD: Bảo hành làm sáng trọn đời, đổi trả 7 ngày..."
            />
          </div>

          <Button type="submit">Lưu Sản Phẩm</Button>
        </form>
      </Card>

      {products.length === 0 ? (
        <EmptyState
          icon={<FolderKanban className="w-5 h-5" />}
          title="Chưa có sản phẩm nào trong Workspace"
          description="Khai báo ít nhất 1 sản phẩm để AI viết kịch bản đúng thông số thật."
        />
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {products.map((p) => (
            <Card key={p.id} className="space-y-2.5">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-[15px] font-bold text-[var(--text-primary)]">
                    {p.name}
                  </h3>
                  {p.material && (
                    <Badge tone="cluster" className="mt-1">
                      {p.material}
                    </Badge>
                  )}
                </div>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={`Xóa sản phẩm ${p.name}`}
                  onClick={() => setDeleteTarget(p)}
                >
                  <Trash2 className="w-4 h-4 text-rose-400" />
                </Button>
              </div>
              <div className="grid grid-cols-2 gap-2 pt-1 text-[12.5px]">
                {Object.entries(p.facts || {}).map(
                  ([k, v]) =>
                    v && (
                      <div key={k} className="truncate text-[var(--text-secondary)]">
                        <span className="text-[var(--text-muted)]">
                          {FACT_LABELS[k] || k}:{" "}
                        </span>
                        {v}
                      </div>
                    )
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      <ModalDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(o) => {
          if (!o) setDeleteTarget(null);
        }}
        title="Ẩn sản phẩm khỏi danh mục"
        description={
          deleteTarget
            ? `Bạn có chắc muốn ẩn sản phẩm "${deleteTarget.name}" khỏi Workspace hiện tại không?`
            : ""
        }
      >
        <div className="flex justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="secondary"
            onClick={() => setDeleteTarget(null)}
          >
            Hủy
          </Button>
          <Button
            type="button"
            variant="danger"
            onClick={() => void confirmDelete()}
          >
            Ẩn sản phẩm
          </Button>
        </div>
      </ModalDialog>
    </div>
  );
}
