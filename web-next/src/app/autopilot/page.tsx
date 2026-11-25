"use client";

import React, { useState } from "react";
import { Bot, Play, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import { PageHeader } from "@/components/vc/PageHeader";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  SwitchToggle,
  TextInput,
} from "@/components/ui/form-controls";

interface AutopilotRule {
  id: number;
  name: string;
  enabled: boolean;
  source_mode:
    | "suggestions"
    | "products_ab"
    | "rss_feed"
    | "localize_trends"
    | "muse_video";
  feed_url: string;
  daily_cap: number;
  min_quality_score: number;
  style_preset: string;
  interval_minutes: number;
  last_status: string;
  last_error: string | null;
  total_generated: number;
}

interface AutopilotRun {
  id: number;
  rule_id: number;
  source_summary: string;
  video_id: number | null;
  status: string;
  detail: string;
  created_at: string;
}

export default function AutopilotPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [name, setName] = useState("");
  const [sourceMode, setSourceMode] =
    useState<AutopilotRule["source_mode"]>("products_ab");
  const [feedUrl, setFeedUrl] = useState("");
  const [dailyCap, setDailyCap] = useState(3);
  const [minScore, setMinScore] = useState(8.0);
  const [msg, setMsg] = useState("");

  const { data, error: err, setError: setErr, reload: load } = useApiQuery<{
    rules: AutopilotRule[];
    runs: AutopilotRun[];
  }>(
    async (signal) => {
      const [rRes, runRes] = await Promise.all([
        apiFetch<{ rules: AutopilotRule[] }>(
          `/api/v1/autopilot/rules?workspace_id=${activeWorkspaceId}`,
          { signal }
        ),
        apiFetch<{ runs: AutopilotRun[] }>(
          `/api/v1/autopilot/runs?workspace_id=${activeWorkspaceId}`,
          { signal }
        ),
      ]);
      return { rules: rRes.rules || [], runs: runRes.runs || [] };
    },
    [activeWorkspaceId],
    { fallbackError: "Lỗi tải Kênh tự động" }
  );

  const rules = data?.rules || [];
  const runs = data?.runs || [];

  const createRule = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      await apiFetch("/api/v1/autopilot/rules", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          name,
          source_mode: sourceMode,
          feed_url: feedUrl,
          daily_cap: dailyCap,
          min_quality_score: minScore,
        }),
      });
      setName("");
      setFeedUrl("");
      setMsg("Đã thêm quy tắc Kênh tự động mới.");
      toast.success("Đã lưu quy tắc tự động.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo quy tắc");
    }
  };

  const triggerRule = async (id: number) => {
    const res = await apiFetch<{ job_id: number }>(
      `/api/v1/autopilot/rules/${id}/trigger`,
      {
        method: "POST",
        body: JSON.stringify({ sync: false, force: true }),
      }
    );
    const m = `Đã kích hoạt quy tắc #${id} (Tác vụ #${res.job_id}).`;
    setMsg(m);
    toast.info(m);
  };

  const toggleRule = async (r: AutopilotRule) => {
    await apiFetch(`/api/v1/autopilot/rules/${r.id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled: !r.enabled }),
    });
    await load();
  };

  const removeRule = async (id: number) => {
    await apiFetch(`/api/v1/autopilot/rules/${id}`, { method: "DELETE" });
    toast.success("Đã xóa quy tắc tự động.");
    await load();
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <PageHeader
        icon={<Bot className="w-5 h-5" />}
        title="Kênh Tự Động Sản Xuất & Lên Lịch (Autopilot)"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {rules.length} quy tắc • {runs.length} lượt chạy
          </Badge>
        }
        description="Tự động lấy nguồn từ Sản phẩm, Đề xuất xu hướng hoặc RSS → Dựng video → Kiểm định kỹ thuật → Tự xếp lịch đăng khi vượt điểm tối thiểu."
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
        <form onSubmit={createRule} className="space-y-4">
          <SectionHeading>
            <Plus className="w-4 h-4 text-[var(--c-icon)]" /> Tạo Quy Tắc Tự Động Mới
          </SectionHeading>

          <div className="grid md:grid-cols-4 gap-3.5">
            <div>
              <FieldLabel htmlFor="ap-name">Tên luồng tự động *</FieldLabel>
              <TextInput
                id="ap-name"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="VD: Lịch đăng Shorts mỗi sáng"
              />
            </div>
            <div>
              <FieldLabel htmlFor="ap-mode">Nguồn kịch bản</FieldLabel>
              <SelectBox
                id="ap-mode"
                value={sourceMode}
                onChange={(e) =>
                  setSourceMode(e.target.value as AutopilotRule["source_mode"])
                }
              >
                <option value="products_ab">Biến thể Sản phẩm A/B</option>
                <option value="suggestions">Đề xuất từ Xu hướng</option>
                <option value="rss_feed">Nguồn tin RSS / Atom</option>
                <option value="localize_trends">Việt hóa Xu hướng</option>
                <option value="muse_video">Clip Muse AI tự động (Full AI)</option>
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="ap-cap">Giới hạn video / ngày</FieldLabel>
              <TextInput
                id="ap-cap"
                type="number"
                min={1}
                max={20}
                value={dailyCap}
                onChange={(e) => setDailyCap(Number(e.target.value))}
                className="tabular-nums"
              />
            </div>
            <div>
              <FieldLabel htmlFor="ap-score">Điểm tối thiểu tự đăng</FieldLabel>
              <TextInput
                id="ap-score"
                type="number"
                step="0.1"
                min={1}
                max={10}
                value={minScore}
                onChange={(e) => setMinScore(Number(e.target.value))}
                className="tabular-nums"
              />
            </div>
          </div>

          {sourceMode === "rss_feed" && (
            <div>
              <FieldLabel htmlFor="ap-rss">Địa chỉ nguồn RSS / Atom *</FieldLabel>
              <TextInput
                id="ap-rss"
                required
                value={feedUrl}
                onChange={(e) => setFeedUrl(e.target.value)}
                placeholder="https://..."
              />
            </div>
          )}

          <Button type="submit">Lưu Quy Tắc</Button>
        </form>
      </Card>

      <Card className="space-y-3.5">
        <SectionHeading className="tabular-nums">
          Danh sách Quy tắc ({rules.length})
        </SectionHeading>
        {rules.length === 0 ? (
          <EmptyState title="Chưa có quy tắc tự động nào" />
        ) : (
          <div className="space-y-2.5">
            {rules.map((r) => (
              <div
                key={r.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5"
              >
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <strong className="text-[14px] text-[var(--text-primary)]">
                      {r.name}
                    </strong>
                    <Badge tone="sky">{r.source_mode}</Badge>
                    <Badge tone="neutral" className="tabular-nums">
                      Tối đa {r.daily_cap}/ngày • Điểm ≥ {r.min_quality_score.toFixed(1)}
                    </Badge>
                  </div>
                  <div className="mt-1 text-[12px] text-[var(--text-muted)] tabular-nums">
                    Trạng thái cuối: {r.last_status} • Đã xuất: {r.total_generated} video
                    {r.last_error ? ` • Lỗi: ${r.last_error}` : ""}
                  </div>
                </div>

                <div className="flex items-center gap-2.5">
                  <SwitchToggle
                    checked={r.enabled}
                    onCheckedChange={() => void toggleRule(r)}
                    aria-label={`Bật hoặc tắt quy tắc ${r.name}`}
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => void triggerRule(r.id)}
                  >
                    <Play className="w-3.5 h-3.5 text-[var(--c-icon)]" /> Chạy ngay
                  </Button>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label={`Xóa quy tắc ${r.name}`}
                    onClick={() => void removeRule(r.id)}
                  >
                    <Trash2 className="w-4 h-4 text-rose-400" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="space-y-3">
        <SectionHeading className="tabular-nums">
          Nhật ký Chạy Tự Động ({runs.length})
        </SectionHeading>
        {runs.length === 0 ? (
          <p className="text-[13px] text-[var(--text-muted)]">
            Chưa có lượt chạy tự động nào được ghi nhận.
          </p>
        ) : (
          <div className="divide-y divide-[var(--border-subtle)]">
            {runs.map((run) => (
              <div
                key={run.id}
                className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-[13px]"
              >
                <span className="text-[var(--text-secondary)]">
                  Quy tắc #{run.rule_id} • {run.source_summary || "—"} ({run.detail})
                </span>
                <Badge tone={run.status === "failed" ? "rose" : "emerald"}>
                  {run.status}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
