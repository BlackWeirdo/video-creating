"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  MessageSquarePlus,
  Play,
  RefreshCw,
  Scissors,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import type { MuseTask } from "@/app/muse/types";
import { formatMuseTaskStatus, mapMuseErrorToVi } from "@/lib/muse-helpers";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextareaBox } from "@/components/ui/form-controls";
import { ModalDialog } from "@/components/ui/overlays";

export function MuseQueueAndLibrary({
  tasks,
  onReload,
  onError,
}: {
  tasks: MuseTask[];
  onReload: () => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [filterKind, setFilterKind] = useState<string>("all");
  const [continueTarget, setContinueTarget] = useState<MuseTask | null>(null);
  const [continuePrompt, setContinuePrompt] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const visible = tasks.filter(
    (t) => filterKind === "all" || t.kind === filterKind
  );

  const dispatchNow = async () => {
    onError("");
    try {
      await apiFetch("/api/v1/muse/dispatch", { method: "POST" });
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Lỗi điều phối Muse");
    }
  };

  const cancelTask = async (id: number) => {
    setBusyId(id);
    try {
      const res = await apiFetch<{ warning?: string }>(
        `/api/v1/muse/tasks/${id}/cancel`,
        { method: "POST" }
      );
      toast.info(res.warning || `Đã hủy tác vụ #${id}.`);
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Không thể hủy tác vụ");
    } finally {
      setBusyId(null);
    }
  };

  const retryTask = async (id: number) => {
    setBusyId(id);
    try {
      await apiFetch(`/api/v1/muse/tasks/${id}/retry`, { method: "POST" });
      void apiFetch("/api/v1/muse/dispatch", { method: "POST" }).catch(() => {});
      toast.success(`Đã xếp thử lại tác vụ #${id} (đổi idempotency_key mới).`);
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Không thể thử lại");
    } finally {
      setBusyId(null);
    }
  };

  const submitContinue = async () => {
    if (!continueTarget || !continuePrompt.trim()) return;
    try {
      await apiFetch(`/api/v1/muse/tasks/${continueTarget.id}/continue`, {
        method: "POST",
        body: JSON.stringify({ prompt: continuePrompt }),
      });
      void apiFetch("/api/v1/muse/dispatch", { method: "POST" }).catch(() => {});
      setContinueTarget(null);
      setContinuePrompt("");
      toast.success("Đã gửi lệnh 'Sửa tiếp' trên cùng luồng hội thoại Muse!");
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Không thể sửa tiếp");
    }
  };

  return (
    <Card className="space-y-4">
      <CardTitleRow>
        <SectionHeading className="tabular-nums">
          Hàng Đợi Đa Luồng &amp; Thư Viện Media Muse ({visible.length})
        </SectionHeading>
        <div className="flex flex-wrap items-center gap-2">
          <SelectBox
            aria-label="Lọc loại tác vụ"
            value={filterKind}
            onChange={(e) => setFilterKind(e.target.value)}
            className="w-40"
          >
            <option value="all">Tất cả loại</option>
            <option value="video">Video</option>
            <option value="image">Ảnh</option>
            <option value="audio">Giọng đọc</option>
          </SelectBox>
          <Button type="button" size="sm" variant="secondary" onClick={() => void dispatchNow()}>
            <Play className="w-3.5 h-3.5" /> Điều phối &amp; Cập nhật ngay
          </Button>
        </div>
      </CardTitleRow>

      {visible.length === 0 ? (
        <EmptyState
          title="Chưa có tác vụ Muse nào trong Workspace này"
          description="Tạo video đơn, nhân bản biến thể song song hoặc chạy Storyboard ở các tab phía trên."
        />
      ) : (
        <div className="grid md:grid-cols-2 gap-3.5">
          {visible.map((t) => {
            const st = formatMuseTaskStatus(t.status, t.partial);
            const friendlyErr = mapMuseErrorToVi(t.error);
            return (
              <div
                key={t.id}
                className="rounded-[12px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5 space-y-2.5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[12px] text-[var(--text-muted)] tabular-nums">
                      #{t.id}
                    </span>
                    <Badge tone="sky" className="uppercase text-[11px]">
                      {t.kind}
                    </Badge>
                    <Badge tone="neutral">{t.model}</Badge>
                  </div>
                  <Badge tone={st.tone}>{st.label}</Badge>
                </div>

                <p className="text-[13px] text-[var(--text-primary)] line-clamp-2">
                  {t.prompt}
                </p>

                {t.media_url && t.kind === "video" && (
                  <video
                    src={t.media_url}
                    controls
                    preload="metadata"
                    className="w-full max-h-56 rounded-[9px] bg-[var(--bg-canvas)] object-contain"
                  />
                )}
                {t.media_url && t.kind === "image" && (
                  <img
                    src={t.media_url}
                    alt={t.prompt}
                    className="w-full max-h-56 rounded-[9px] bg-[var(--bg-canvas)] object-contain"
                  />
                )}
                {t.media_url && t.kind === "audio" && (
                  <audio src={t.media_url} controls className="w-full" />
                )}

                {friendlyErr && (
                  <div className="rounded-[8px] border border-[var(--st-rose-bd)] bg-[var(--st-rose-bg)] px-2.5 py-1.5 text-[12px] text-[var(--st-rose-tx)]">
                    {friendlyErr}
                  </div>
                )}

                <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-[12px] text-[var(--text-muted)]">
                  <span>
                    {t.shot_id
                      ? `Đã nhập Shot #${t.shot_id}`
                      : t.ai_image_id
                        ? `Ảnh AI #${t.ai_image_id}`
                        : `Lần thử #${t.attempt + 1}`}
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {(t.status === "pending" ||
                      t.status === "submitted" ||
                      t.status === "waiting_quota") && (
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={busyId === t.id}
                        onClick={() => void cancelTask(t.id)}
                      >
                        <XCircle className="w-3.5 h-3.5" /> Hủy
                      </Button>
                    )}
                    {(t.status === "failed" || t.status === "cancelled") && (
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        disabled={busyId === t.id}
                        onClick={() => void retryTask(t.id)}
                      >
                        <RefreshCw className="w-3.5 h-3.5" /> Thử lại
                      </Button>
                    )}
                    {t.status === "succeeded" && t.thread_url && t.account_id && (
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setContinueTarget(t);
                          setContinuePrompt("");
                        }}
                      >
                        <MessageSquarePlus className="w-3.5 h-3.5" /> Sửa tiếp
                      </Button>
                    )}
                    {t.shot_id && (
                      <Button asChild size="sm" variant="emerald">
                        <Link href="/editor">
                          <Scissors className="w-3.5 h-3.5" /> Đưa vào Trình dựng
                        </Link>
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <ModalDialog
        open={Boolean(continueTarget)}
        onOpenChange={(o) => {
          if (!o) setContinueTarget(null);
        }}
        title={`Sửa tiếp trên cùng hội thoại Muse (#${continueTarget?.id ?? ""})`}
        description="Hệ thống giữ nguyên thread_url và tài khoản Muse đã tạo cảnh gốc để điều chỉnh chi tiết liền mạch."
      >
        <div className="space-y-3 pt-1">
          <div>
            <FieldLabel htmlFor="cont-prompt">Yêu cầu chỉnh sửa / nối tiếp *</FieldLabel>
            <TextareaBox
              id="cont-prompt"
              rows={3}
              value={continuePrompt}
              onChange={(e) => setContinuePrompt(e.target.value)}
              placeholder="VD: Giữ nguyên nhân vật và bối cảnh, đổi sang góc quay toàn cảnh lúc hoàng hôn..."
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setContinueTarget(null)}
            >
              Đóng
            </Button>
            <Button type="button" onClick={() => void submitContinue()}>
              Gửi lệnh Sửa tiếp
            </Button>
          </div>
        </div>
      </ModalDialog>
    </Card>
  );
}
