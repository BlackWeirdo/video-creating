"use client";

import React, { useState } from "react";
import { CheckCircle2, Cpu, Download } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { LocalModelRow } from "@/app/settings/types";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge, PillTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, TextInput } from "@/components/ui/form-controls";
import { ModalDialog } from "@/components/ui/overlays";

export function LocalModelsManagerTab({
  localModels,
  mirrorBaseUrl,
  setMirrorBaseUrl,
  onReload,
  onMessage,
  onError,
}: {
  localModels: LocalModelRow[];
  mirrorBaseUrl: string;
  setMirrorBaseUrl: (v: string) => void;
  onReload: () => Promise<void>;
  onMessage: (m: string) => void;
  onError: (m: string) => void;
}) {
  const [removeTarget, setRemoveTarget] = useState<LocalModelRow | null>(null);

  const saveMirror = async () => {
    onError("");
    onMessage("");
    try {
      await apiFetch("/api/v1/settings", {
        method: "PUT",
        body: JSON.stringify({
          models: { mirror_base_url: mirrorBaseUrl.trim() },
        }),
      });
      const m = "Đã lưu địa chỉ máy chủ dự phòng (Mirror) tải mô hình.";
      onMessage(m);
      toast.success(m);
      await onReload();
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Lỗi lưu địa chỉ Mirror");
    }
  };

  return (
    <Card tinted className="space-y-4">
      <CardTitleRow>
        <SectionHeading>
          <Cpu className="w-4 h-4 text-[var(--c-icon)]" /> Kho Mô Hình AI Cục Bộ (Kiểm chứng SHA-256 &amp; Chạy thử CPU)
        </SectionHeading>
      </CardTitleRow>

      <div className="flex flex-wrap items-end gap-2.5 rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3">
        <div className="flex-1 min-w-[240px]">
          <FieldLabel htmlFor="mod-mirror">
            Máy chủ tải dự phòng nội bộ (Mirror R2 / CDN tùy chọn)
          </FieldLabel>
          <TextInput
            id="mod-mirror"
            value={mirrorBaseUrl}
            onChange={(e) => setMirrorBaseUrl(e.target.value)}
            placeholder="VD: https://cdn.company.vn/models"
          />
        </div>
        <Button type="button" variant="secondary" onClick={() => void saveMirror()}>
          Lưu địa chỉ Mirror
        </Button>
      </div>

      <div className="grid md:grid-cols-2 gap-3.5">
        {localModels.map((m) => {
          const isNc = (m.license || "").includes("NC");
          let statusLabel = "Chưa tải";
          let statusTone: PillTone = "neutral";
          if (m.status === "downloading") {
            statusLabel = `Đang tải (${Math.round((m.progress || 0) * 100)}%)`;
            statusTone = "sky";
          } else if (m.status === "downloaded") {
            statusLabel = "Đã tải • Chờ chạy thử";
            statusTone = "amber";
          } else if (m.status === "ready") {
            statusLabel = m.smoke_tested ? "Sẵn sàng (đã chạy thử)" : "Sẵn sàng";
            statusTone = "emerald";
          } else if (m.status === "failed") {
            statusLabel = "Lỗi kiểm chứng";
            statusTone = "rose";
          }

          return (
            <div
              key={m.model_id}
              className="flex flex-col justify-between gap-3 rounded-[12px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5"
            >
              <div className="space-y-1.5">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[14px] font-bold text-[var(--text-primary)]">
                    {m.name}
                  </span>
                  {m.license && (
                    <Badge tone={isNc ? "amber" : "neutral"}>{m.license}</Badge>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-2 text-[12px] text-[var(--text-muted)] tabular-nums">
                  <span>{m.category}</span>
                  <span>• ~{m.size_mb} MB</span>
                  <Badge tone={statusTone}>{statusLabel}</Badge>
                </div>

                {m.status === "downloading" && (
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--bg-canvas)]">
                    <div
                      className="h-full bg-[var(--c-solid)] transition-all duration-200"
                      style={{
                        width: `${Math.max(4, Math.round((m.progress || 0) * 100))}%`,
                      }}
                    />
                  </div>
                )}

                {isNc && (
                  <div className="text-[11.5px] text-[var(--st-amber-tx)]">
                    Lưu ý: Giấy phép phi thương mại — chỉ dùng làm đường dịch dự phòng khi mất mạng.
                  </div>
                )}
                {m.missing_python_pkgs && m.missing_python_pkgs.length > 0 && (
                  <div className="text-[11.5px] text-[var(--st-amber-tx)]">
                    Thiếu thư viện: {m.missing_python_pkgs.join(", ")}
                  </div>
                )}
                {m.error && (
                  <div className="text-[12px] text-[var(--st-rose-tx)] break-words">
                    {m.error}
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-2">
                {m.status !== "ready" && (
                  <Button
                    type="button"
                    size="sm"
                    onClick={async () => {
                      onError("");
                      await apiFetch(`/api/v1/models/${m.model_id}/install`, {
                        method: "POST",
                        body: JSON.stringify({}),
                      });
                      const info = `Đã đưa mô hình ${m.name} vào hàng đợi tải & kiểm thử CPU.`;
                      onMessage(info);
                      toast.info(info);
                      await onReload();
                    }}
                  >
                    <Download className="w-3.5 h-3.5" />{" "}
                    {m.status === "downloaded" ? "Tải lại" : "Tải về"}
                  </Button>
                )}

                {m.installed_on_disk && m.status !== "ready" && (
                  <Button
                    type="button"
                    size="sm"
                    variant="emerald"
                    onClick={async () => {
                      onError("");
                      onMessage("");
                      try {
                        await apiFetch(`/api/v1/models/${m.model_id}/verify`, {
                          method: "POST",
                        });
                        const ok = `Mô hình ${m.name} đã vượt qua kiểm thử CPU và sẵn sàng!`;
                        onMessage(ok);
                        toast.success(ok);
                        await onReload();
                      } catch (e2) {
                        onError(
                          e2 instanceof Error ? e2.message : "Kiểm thử mô hình thất bại"
                        );
                        await onReload();
                      }
                    }}
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" /> Chạy thử CPU
                  </Button>
                )}

                {(m.status === "ready" || m.installed_on_disk) && (
                  <Button
                    type="button"
                    size="sm"
                    variant="danger"
                    onClick={() => setRemoveTarget(m)}
                  >
                    Gỡ bỏ
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <ModalDialog
        open={Boolean(removeTarget)}
        onOpenChange={(o) => {
          if (!o) setRemoveTarget(null);
        }}
        title="Xác nhận gỡ mô hình AI cục bộ"
        description={
          removeTarget
            ? `Gỡ tệp mô hình "${removeTarget.name}" (~${removeTarget.size_mb} MB) khỏi ổ cứng? Bạn có thể tải lại bất kỳ lúc nào.`
            : ""
        }
      >
        <div className="flex justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="secondary"
            onClick={() => setRemoveTarget(null)}
          >
            Hủy
          </Button>
          <Button
            type="button"
            variant="danger"
            onClick={async () => {
              if (!removeTarget) return;
              await apiFetch(`/api/v1/models/${removeTarget.model_id}`, {
                method: "DELETE",
              });
              toast.success(`Đã gỡ mô hình ${removeTarget.name}.`);
              setRemoveTarget(null);
              await onReload();
            }}
          >
            Gỡ mô hình
          </Button>
        </div>
      </ModalDialog>
    </Card>
  );
}
