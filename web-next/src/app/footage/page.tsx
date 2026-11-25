"use client";

import React, { useState } from "react";
import { Film, FolderInput, Save, Upload } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import { PageHeader } from "@/components/vc/PageHeader";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, SwitchToggle, TextInput } from "@/components/ui/form-controls";

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
  const [localPath, setLocalPath] = useState("");
  const [noProduct, setNoProduct] = useState(true);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [focusMap, setFocusMap] = useState<Record<number, number>>({});
  const [msg, setMsg] = useState("");

  const { data, error: err, setError: setErr, reload: load } = useApiQuery<{
    footage: FootageItem[];
    shots: ShotItem[];
  }>(
    async (signal) => {
      const [fRes, sRes] = await Promise.all([
        apiFetch<{ footage: FootageItem[] }>(
          `/api/v1/footage?workspace_id=${activeWorkspaceId}`,
          { signal }
        ),
        apiFetch<{ shots: ShotItem[] }>(
          `/api/v1/shots?workspace_id=${activeWorkspaceId}`,
          { signal }
        ),
      ]);
      return { footage: fRes.footage || [], shots: sRes.shots || [] };
    },
    [activeWorkspaceId],
    {
      fallbackError: "Lỗi tải kho Footage & Shot",
      onSuccess: (bundle) => {
        const fm: Record<number, number> = {};
        for (const s of bundle.shots) {
          fm[s.id] = s.focus_x ?? 0.5;
        }
        setFocusMap(fm);
      },
    }
  );

  const footage = data?.footage || [];
  const shots = data?.shots || [];

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
      setMsg("Đã tải lên video gốc và xếp hàng phân tích cảnh.");
      toast.success("Đã tải lên video quay thô.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Tải lên thất bại");
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
      setMsg("Đã nạp tệp video từ ổ đĩa cục bộ.");
      toast.success("Đã nạp tệp cục bộ.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Nạp tệp cục bộ thất bại");
    }
  };

  const saveFocus = async (shotId: number) => {
    await apiFetch(`/api/v1/shots/${shotId}`, {
      method: "PATCH",
      body: JSON.stringify({ focus_x: focusMap[shotId] ?? 0.5 }),
    });
    const m = `Đã lưu tâm khung dọc cho Shot #${shotId}.`;
    setMsg(m);
    toast.success(m);
    await load();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        icon={<Film className="w-5 h-5" />}
        title="Kho Footage Quay Thật & Thư Viện Shot"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {footage.length} video gốc • {shots.length} cảnh cắt
          </Badge>
        }
        description="Nạp video quay thô thực tế của thương hiệu để AI tự tách cảnh (Shot) và tinh chỉnh tâm khung ngang sang dọc 9:16."
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

      <div className="grid md:grid-cols-2 gap-4">
        <Card tinted>
          <form onSubmit={handleUpload} className="space-y-3.5">
            <SectionHeading>
              <Upload className="w-4 h-4 text-[var(--c-icon)]" /> Tải lên Video Quay Thô
            </SectionHeading>
            <div>
              <FieldLabel htmlFor="ft-file">Chọn tệp video (.mp4, .mov, .mkv)</FieldLabel>
              <input
                id="ft-file"
                type="file"
                accept=".mp4,.mov,.mkv,.webm"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                className="block w-full rounded-[8px] border border-[var(--border-strong)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-[var(--text-secondary)] file:mr-3 file:rounded-md file:border file:border-[var(--border-subtle)] file:bg-[var(--bg-elevated)] file:px-3 file:py-1 file:text-[12px] file:font-semibold file:text-[var(--text-primary)] file:cursor-pointer"
              />
            </div>

            <div className="flex items-center gap-2.5">
              <SwitchToggle
                id="ft-broll"
                checked={noProduct}
                onCheckedChange={setNoProduct}
              />
              <label
                htmlFor="ft-broll"
                className="text-[13px] text-[var(--text-secondary)] cursor-pointer"
              >
                Cảnh hậu trường / quy trình (không gắn sản phẩm cố định)
              </label>
            </div>

            <Button type="submit" disabled={!uploadFile}>
              Tải lên &amp; Phân tích Cảnh
            </Button>
          </form>
        </Card>

        <Card>
          <form onSubmit={handleImportLocal} className="space-y-3.5">
            <SectionHeading>
              <FolderInput className="w-4 h-4 text-[var(--c-icon)]" /> Nạp Đường Dẫn Ổ Đĩa Cục Bộ
            </SectionHeading>
            <div>
              <FieldLabel htmlFor="ft-local-path">
                Đường dẫn tuyệt đối tới tệp trên máy *
              </FieldLabel>
              <TextInput
                id="ft-local-path"
                required
                value={localPath}
                onChange={(e) => setLocalPath(e.target.value)}
                placeholder="VD: D:\Footage\quay_san_pham_01.mp4"
              />
            </div>
            <Button type="submit" variant="secondary">
              Nạp Tệp Cục Bộ
            </Button>
          </form>
        </Card>
      </div>

      <Card className="space-y-3.5">
        <SectionHeading className="tabular-nums">
          Danh sách Video Gốc ({footage.length})
        </SectionHeading>
        {footage.length === 0 ? (
          <EmptyState
            icon={<Film className="w-5 h-5" />}
            title="Chưa có video quay thô nào"
            description="Tải lên các đoạn quay sản phẩm thật để hệ thống tự cắt thành kho Shot."
          />
        ) : (
          <div className="grid md:grid-cols-3 gap-3.5">
            {footage.map((f) => (
              <div
                key={f.id}
                className="rounded-[12px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 space-y-2"
              >
                {f.media_url && (
                  <div className="aspect-video w-full overflow-hidden rounded-[8px] bg-black">
                    <video
                      src={f.media_url}
                      controls
                      className="h-full w-full object-cover"
                    />
                  </div>
                )}
                <div className="flex items-center justify-between text-[13px] font-semibold text-[var(--text-primary)] tabular-nums">
                  <span>Footage #{f.id}</span>
                  <Badge tone="neutral">
                    {f.duration_s.toFixed(1)}s • {f.orientation}
                  </Badge>
                </div>
                <div className="text-[12px] text-[var(--text-muted)] tabular-nums">
                  Trạng thái: {f.status} ({f.width}×{f.height})
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="space-y-3.5">
        <SectionHeading className="tabular-nums">
          Kho Cảnh Cắt Shot ({shots.length})
        </SectionHeading>
        {shots.length === 0 ? (
          <EmptyState title="Chưa có cảnh cắt Shot nào" />
        ) : (
          <div className="grid md:grid-cols-2 gap-3.5">
            {shots.map((s) => (
              <div
                key={s.id}
                className="rounded-[12px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5 space-y-2.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <strong className="text-[13.5px] text-[var(--text-primary)] tabular-nums">
                    Shot #{s.id} ({s.start_s.toFixed(1)}s – {s.end_s.toFixed(1)}s)
                  </strong>
                  <Badge tone="amber" className="tabular-nums">
                    Chất lượng {s.quality}/5
                  </Badge>
                </div>
                <div className="text-[13px] text-[var(--text-secondary)]">
                  {s.description || "Chưa có mô tả cảnh"}
                </div>
                <div className="flex items-center gap-3 pt-1">
                  <label
                    htmlFor={`focus-shot-${s.id}`}
                    className="text-[12px] text-[var(--text-muted)] shrink-0 tabular-nums"
                  >
                    Tâm X ({(focusMap[s.id] ?? 0.5).toFixed(2)}):
                  </label>
                  <input
                    id={`focus-shot-${s.id}`}
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={focusMap[s.id] ?? 0.5}
                    onChange={(e) =>
                      setFocusMap((prev) => ({
                        ...prev,
                        [s.id]: Number(e.target.value),
                      }))
                    }
                    className="flex-1 accent-[var(--c-solid)]"
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => void saveFocus(s.id)}
                  >
                    <Save className="w-3.5 h-3.5" /> Lưu
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
