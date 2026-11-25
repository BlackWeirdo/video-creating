"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Clapperboard,
  DollarSign,
  Film,
  Flame,
  FolderKanban,
  Languages,
  LayoutDashboard,
  Scissors,
} from "lucide-react";
import { apiFetch, JobRecord, useWorkspace, Workspace } from "@/lib/api";
import { NAV_CLUSTERS } from "@/config/navigation";
import { PageHeader } from "@/components/vc/PageHeader";
import { PolicyBadge } from "@/components/vc/PolicyBadge";
import { EmptyState, StatCard } from "@/components/vc/StatCard";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge, PillTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface DashboardData {
  workspace_id: number;
  workspace: Workspace | null;
  counts: {
    products: number;
    footage: number;
    shots: number;
    trends: number;
    suggestions_new: number;
    videos_total: number;
    videos_by_status: Record<string, number>;
    accounts: number;
    posts_scheduled: number;
    posts_posted: number;
  };
  ai_budget: {
    day: string;
    spent_usd: number;
    limit_usd: number;
  };
}

const JOB_STATUS_TONE: Record<string, { label: string; tone: PillTone }> = {
  queued: { label: "Đang chờ", tone: "neutral" },
  running: { label: "Đang xử lý", tone: "cluster" },
  waiting_quota: { label: "Chờ hạn mức", tone: "amber" },
  done: { label: "Hoàn tất", tone: "emerald" },
  failed: { label: "Gặp lỗi", tone: "rose" },
};

const CLUSTER_ICONS = {
  source: Flame,
  produce: Clapperboard,
  adapt: Languages,
  edit: Scissors,
  publish: CheckCircle2,
} as const;

export default function DashboardPage() {
  const { activeWorkspaceId, activeWorkspace } = useWorkspace();
  const [data, setData] = useState<DashboardData | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobRecord[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    apiFetch<DashboardData>(`/api/v1/dashboard?workspace_id=${activeWorkspaceId}`)
      .then((res) => {
        if (active) {
          setData(res);
          setError("");
        }
      })
      .catch((err) => {
        if (active)
          setError(err instanceof Error ? err.message : "Không thể tải dữ liệu tổng quan");
      });
    return () => {
      active = false;
    };
  }, [activeWorkspaceId]);

  useEffect(() => {
    const onSnapshot = (ev: Event) => {
      const detail = (ev as CustomEvent<{ recent_jobs?: JobRecord[] }>).detail;
      if (Array.isArray(detail?.recent_jobs)) {
        setRecentJobs(detail.recent_jobs.slice(0, 6));
      }
    };
    window.addEventListener("vc:queue-snapshot", onSnapshot);
    return () => window.removeEventListener("vc:queue-snapshot", onSnapshot);
  }, []);

  const counts = data?.counts;
  const pendingCount = counts?.videos_by_status?.pending_approval || 0;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        icon={<LayoutDashboard className="w-5 h-5" />}
        title={`Tổng quan Studio — ${activeWorkspace?.name || "Workspace Mặc định"}`}
        badges={
          <>
            <PolicyBadge policy={activeWorkspace?.content_policy} showDetail />
            <Badge tone="neutral">
              Khung hình: {activeWorkspace?.default_aspect_ratio || "9:16"}
            </Badge>
          </>
        }
        description="Theo dõi tài nguyên sản phẩm, tiến độ sản xuất video, hàng chờ duyệt và truy cập nhanh vào 5 cụm chức năng chuyên biệt."
        actions={
          <>
            <Button asChild variant="secondary">
              <Link href="/localize">
                <Languages className="w-4 h-4" /> Việt hóa &amp; Remix
              </Link>
            </Button>
            <Button asChild>
              <Link href="/videos">
                <Clapperboard className="w-4 h-4" /> Tạo Video Mới
              </Link>
            </Button>
          </>
        }
      />

      {error && (
        <div
          role="alert"
          className="rounded-[11px] border border-[var(--st-rose-bd)] bg-[var(--st-rose-bg)] px-4 py-3 text-[13px] text-[var(--st-rose-tx)]"
        >
          {error}
        </div>
      )}

      {/* 4 Core KPI StatCards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Sản phẩm & Dữ kiện"
          value={counts?.products ?? "—"}
          subtitle="Đã xác thực thông tin gốc"
          href="/products"
          icon={<FolderKanban className="w-4 h-4" />}
        />
        <StatCard
          title="Kho Footage & Shot"
          value={`${counts?.footage ?? 0} / ${counts?.shots ?? 0}`}
          subtitle="Video gốc / Cảnh cắt sẵn"
          href="/footage"
          icon={<Film className="w-4 h-4" />}
        />
        <StatCard
          title="Video Chờ Duyệt"
          value={pendingCount}
          subtitle={`Tổng đã tạo: ${counts?.videos_total ?? 0} video`}
          href="/approval"
          icon={<CheckCircle2 className="w-4 h-4" />}
        />
        <StatCard
          title="Chi tiêu AI hôm nay"
          value={`$${(data?.ai_budget?.spent_usd ?? 0).toFixed(2)}`}
          subtitle={`Hạn mức ngày: $${(data?.ai_budget?.limit_usd ?? 5).toFixed(2)}`}
          href="/settings"
          icon={<DollarSign className="w-4 h-4" />}
        />
      </div>

      {/* 5 Vivid Cluster Shortcut Cards */}
      <section aria-labelledby="clusters-heading" className="space-y-3">
        <SectionHeading id="clusters-heading">
          5 Cụm Chức Năng Studio
        </SectionHeading>
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {NAV_CLUSTERS.map((cluster) => {
            const CIcon = CLUSTER_ICONS[cluster.id];
            const summaryLine =
              cluster.id === "source"
                ? `${counts?.trends ?? 0} xu hướng • ${counts?.suggestions_new ?? 0} gợi ý mới`
                : cluster.id === "publish"
                  ? `${counts?.accounts ?? 0} kênh • ${counts?.posts_scheduled ?? 0} lịch hẹn • ${counts?.posts_posted ?? 0} đã đăng`
                  : `${cluster.items.length} công cụ chuyên biệt`;

            return (
              <div key={cluster.id} data-cluster={cluster.id}>
                <Card tinted className="h-full flex flex-col justify-between gap-3">
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="inline-flex items-center gap-2 text-[15px] font-bold text-[var(--text-primary)]">
                        <span className="inline-flex h-8 w-8 items-center justify-center rounded-[9px] border border-[var(--c-bd)] bg-[var(--c-soft)] text-[var(--c-icon)]">
                          <CIcon className="w-4 h-4" />
                        </span>
                        {cluster.label}
                      </span>
                      <Badge tone="cluster">{summaryLine}</Badge>
                    </div>

                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {cluster.items.map((it) => (
                        <Link
                          key={it.href}
                          href={it.href}
                          className="inline-flex items-center gap-1 rounded-[8px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-2.5 py-1 text-[12.5px] font-medium text-[var(--text-secondary)] hover:border-[var(--c-bd)] hover:text-[var(--c-tx)] transition-colors"
                        >
                          <span>{it.label}</span>
                          <ArrowRight className="w-3 h-3 opacity-70" />
                        </Link>
                      ))}
                    </div>
                  </div>
                </Card>
              </div>
            );
          })}
        </div>
      </section>

      {/* Recent Background Jobs */}
      <Card className="space-y-3">
        <CardTitleRow>
          <SectionHeading>
            <Activity className="w-4 h-4 text-[var(--c-icon)]" /> Tác vụ xử lý gần đây
          </SectionHeading>
          <Badge tone="neutral" className="tabular-nums">
            {recentJobs.length} tác vụ mới nhất
          </Badge>
        </CardTitleRow>

        {recentJobs.length === 0 ? (
          <EmptyState
            icon={<Clapperboard className="w-5 h-5" />}
            title="Chưa có tác vụ nào chạy gần đây"
            description="Hãy quét xu hướng mới, tải cảnh quay sản phẩm hoặc mở Studio Việt hóa để bắt đầu dây chuyền sản xuất."
            action={
              <Button asChild size="sm">
                <Link href="/localize">Mở Việt hóa &amp; Remix →</Link>
              </Button>
            }
          />
        ) : (
          <div className="divide-y divide-[var(--border-subtle)]">
            {recentJobs.map((j) => {
              const st = JOB_STATUS_TONE[j.status] || {
                label: j.status,
                tone: "neutral" as PillTone,
              };
              return (
                <div
                  key={j.id}
                  className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-[13px]"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="font-mono text-[12px] text-[var(--text-muted)] tabular-nums">
                      #{j.id}
                    </span>
                    <span className="font-semibold text-[var(--text-primary)]">
                      {j.kind}
                    </span>
                    {j.step && (
                      <span className="truncate text-[var(--text-muted)]">
                        — {j.step}
                      </span>
                    )}
                  </div>
                  <Badge tone={st.tone}>{st.label}</Badge>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
