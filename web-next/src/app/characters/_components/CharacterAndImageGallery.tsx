"use client";

import React from "react";
import { Image as ImageIcon, Scissors, Upload } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import type { AIImageRow, CharacterRow } from "@/app/characters/types";
import { SimulationBadge } from "@/components/SimulationBadge";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function CharacterAndImageGallery({
  characters,
  images,
  onReload,
  onMessage,
  onError,
}: {
  characters: CharacterRow[];
  images: AIImageRow[];
  onReload: () => Promise<void>;
  onMessage: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const uploadCharRef = async (charId: number, file: File) => {
    onError("");
    const fd = new FormData();
    fd.append("file", file);
    try {
      await apiFetch(`/api/v1/characters/${charId}/upload-ref`, {
        method: "POST",
        body: fd,
      });
      const m = `Đã cập nhật ảnh tham chiếu cho Nhân vật #${charId}.`;
      onMessage(m);
      toast.success(m);
      await onReload();
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Lỗi tải ảnh tham chiếu");
    }
  };

  return (
    <div className="grid md:grid-cols-2 gap-4">
      <Card className="space-y-3">
        <SectionHeading className="tabular-nums">
          Nhân vật ({characters.length})
        </SectionHeading>
        {characters.length === 0 ? (
          <EmptyState title="Chưa tạo nhân vật cố định nào" />
        ) : (
          <div className="space-y-2.5">
            {characters.map((c) => (
              <div
                key={c.id}
                className="rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5 space-y-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <strong className="text-[14px] text-[var(--text-primary)]">
                    {c.name}
                  </strong>
                  <Badge tone="cluster" className="tabular-nums">
                    Seed {c.seed}
                  </Badge>
                </div>
                <div className="text-[12.5px] text-[var(--text-muted)]">
                  {c.appearance_prompt || "—"}
                </div>
                <div className="flex flex-wrap gap-2 items-center">
                  <label className="inline-flex min-h-[32px] items-center gap-1.5 rounded-[8px] border border-[var(--border-strong)] bg-[var(--bg-card)] px-2.5 py-1 text-[12px] font-semibold text-[var(--text-primary)] hover:border-[var(--c-bd)] cursor-pointer">
                    <Upload className="w-3.5 h-3.5 text-[var(--c-icon)]" /> Ảnh gốc
                    <input
                      type="file"
                      accept=".png,.jpg,.jpeg,.webp"
                      className="sr-only"
                      onChange={(ev) => {
                        const f = ev.target.files?.[0];
                        if (f) void uploadCharRef(c.id, f);
                      }}
                    />
                  </label>
                  {c.ref_image_path && (
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={async () => {
                        await apiFetch(`/api/v1/characters/${c.id}/cutout`, {
                          method: "POST",
                        });
                        onMessage(
                          `Đã tách nền PNG (Rembg U2Net) cho nhân vật #${c.id}.`
                        );
                        await onReload();
                      }}
                    >
                      <Scissors className="w-3.5 h-3.5" /> Tách nền PNG
                    </Button>
                  )}
                </div>
                <SimulationBadge flags={c.cutout_simulation_flags} />
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="space-y-3">
        <SectionHeading className="tabular-nums">
          <ImageIcon className="w-4 h-4 text-[var(--c-icon)]" /> Kho Ảnh Cảnh Nền ({images.length})
        </SectionHeading>
        {images.length === 0 ? (
          <EmptyState title="Chưa có ảnh cảnh nền nào" />
        ) : (
          <div className="grid sm:grid-cols-2 gap-3">
            {images.map((im) => (
              <div
                key={im.id}
                className="rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 space-y-2"
              >
                {im.image_path && (
                  <div className="aspect-video w-full overflow-hidden rounded-[8px] bg-black">
                    <img
                      src={`/files/${im.image_path}`}
                      alt={im.prompt}
                      className="h-full w-full object-cover"
                    />
                  </div>
                )}
                <div className="text-[12.5px] text-[var(--text-primary)] line-clamp-2">
                  {im.prompt}
                </div>
                <div className="text-[11.5px] text-[var(--text-muted)] tabular-nums">
                  Seed {im.seed} • Shot: {im.motion_shot_id ?? "chưa tạo"}
                </div>
                <SimulationBadge flags={im.simulation_flags} />
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
