"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Check, Play, RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { PageHeader } from "@/components/vc/PageHeader";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, TextareaBox, TextInput } from "@/components/ui/form-controls";

interface StudioSession {
  id: number;
  video_id: number | null;
  prompt: string;
  status: string;
  cost_usd: number;
  error: string | null;
  created_at: string;
}

export default function StudioPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [sessions, setSessions] = useState<StudioSession[]>([]);
  const [prompt, setPrompt] = useState("");
  const [reviseMap, setReviseMap] = useState<Record<number, string>>({});
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<{ sessions: StudioSession[] }>(
        `/api/v1/studio/sessions?workspace_id=${activeWorkspaceId}`
      );
      setSessions(data.sessions || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Studio AI");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const startSession = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ session: StudioSession; job_id: number }>(
        "/api/v1/studio/sessions",
        {
          method: "POST",
          body: JSON.stringify({ workspace_id: activeWorkspaceId, prompt }),
        }
      );
      setPrompt("");
      const m = `Đã khởi chạy phiên thiết kế #${res.session.id} (Tác vụ #${res.job_id}).`;
      setMsg(m);
      toast.info(m);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo phiên Studio");
    }
  };

  const confirmPlan = async (id: number) => {
    await apiFetch(`/api/v1/studio/sessions/${id}/confirm`, { method: "POST" });
    const m = `Đã xác nhận kịch bản phiên #${id}, bắt đầu kết xuất đồ họa chuyển động.`;
    setMsg(m);
    toast.success(m);
    await load();
  };

  const reviseSession = async (id: number) => {
    const rev = reviseMap[id] || "";
    if (!rev.trim()) return;
    await apiFetch(`/api/v1/studio/sessions/${id}/revise`, {
      method: "POST",
      body: JSON.stringify({ prompt: rev }),
    });
    setReviseMap((prev) => ({ ...prev, [id]: "" }));
    const m = `Đã gửi yêu cầu tinh chỉnh cho phiên #${id}.`;
    setMsg(m);
    toast.info(m);
    await load();
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <PageHeader
        icon={<Sparkles className="w-5 h-5" />}
        title="Studio Đồ Họa Chuyển Động AI (Remotion)"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {sessions.length} phiên thiết kế
          </Badge>
        }
        description="Tự động thiết kế hiệu ứng chữ động, chuyển cảnh và bố cục đồ họa trên cảnh quay thật; tạm dừng chờ bạn duyệt trước khi kết xuất."
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

      <Card tinted>
        <form onSubmit={startSession} className="space-y-3.5">
          <SectionHeading>Khởi Tạo Phiên Thiết Kế Đồ Họa Mới</SectionHeading>
          <div>
            <FieldLabel htmlFor="rm-prompt">
              Mô tả phong cách chuyển cảnh, chữ tiêu đề và nhịp điệu mong muốn *
            </FieldLabel>
            <TextareaBox
              id="rm-prompt"
              required
              rows={3}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="VD: Chuyển cảnh sang trọng cho bộ sưu tập trang sức bạc, chữ tiêu đề nổi bật ở 2 giây đầu..."
            />
          </div>
          <Button type="submit">
            <Play className="w-4 h-4" /> Chạy Phiên Thiết Kế
          </Button>
        </form>
      </Card>

      {sessions.length === 0 ? (
        <EmptyState
          icon={<Sparkles className="w-5 h-5" />}
          title="Chưa có phiên thiết kế nào"
          description="Nhập mô tả ý tưởng ở trên để AI sinh bố cục chuyển động."
        />
      ) : (
        <div className="space-y-3.5">
          {sessions.map((s) => (
            <Card key={s.id} className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <strong className="text-[14.5px] text-[var(--text-primary)]">
                  Phiên #{s.id} (Video #{s.video_id ?? "—"})
                </strong>
                <Badge tone="cluster" className="tabular-nums">
                  {s.status} • ${s.cost_usd.toFixed(3)}
                </Badge>
              </div>
              <div className="text-[13.5px] text-[var(--text-secondary)]">
                {s.prompt}
              </div>
              {s.error && (
                <div className="text-[12.5px] text-[var(--st-rose-tx)]">
                  {s.error}
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2.5 pt-1">
                {s.status === "awaiting_confirm" && (
                  <Button
                    type="button"
                    size="sm"
                    variant="emerald"
                    onClick={() => void confirmPlan(s.id)}
                  >
                    <Check className="w-3.5 h-3.5" /> Xác nhận &amp; Xuất Video
                  </Button>
                )}
                {["awaiting_confirm", "done", "failed"].includes(s.status) && (
                  <div className="flex flex-1 gap-2 min-w-[240px]">
                    <TextInput
                      aria-label={`Yêu cầu sửa lại cho phiên #${s.id}`}
                      value={reviseMap[s.id] || ""}
                      onChange={(e) =>
                        setReviseMap((prev) => ({
                          ...prev,
                          [s.id]: e.target.value,
                        }))
                      }
                      placeholder="Nhập yêu cầu chỉnh sửa thêm..."
                      className="min-h-[34px] py-1"
                    />
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={() => void reviseSession(s.id)}
                    >
                      <RefreshCw className="w-3.5 h-3.5" /> Tinh chỉnh
                    </Button>
                  </div>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
