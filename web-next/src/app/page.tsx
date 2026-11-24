"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  CheckCircle2,
  Clapperboard,
  DollarSign,
  Film,
  Flame,
  FolderKanban,
  Sparkles,
} from "lucide-react";
import { apiFetch, useWorkspace, Workspace } from "@/lib/api";

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

export default function DashboardPage() {
  const { activeWorkspaceId, activeWorkspace } = useWorkspace();
  const [data, setData] = useState<DashboardData | null>(null);
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
        if (active) setError(err instanceof Error ? err.message : "Lỗi tải dashboard");
      });
    return () => {
      active = false;
    };
  }, [activeWorkspaceId]);

  const counts = data?.counts;
  const pendingCount = counts?.videos_by_status?.pending_approval || 0;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Tổng quan Studio — {activeWorkspace?.name || "Workspace Mặc định"}
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Chính sách nội dung:{" "}
            <span className="text-slate-200 font-medium">
              {activeWorkspace?.content_policy || "strict_footage"}
            </span>{" "}
            • Duyệt:{" "}
            <span className="text-slate-200 font-medium">
              {activeWorkspace?.approval_mode || "single"}
            </span>{" "}
            • Khung hình ưu tiên:{" "}
            <span className="text-slate-200 font-medium">
              {activeWorkspace?.default_aspect_ratio || "9:16"}
            </span>
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            href="/videos"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-xs"
          >
            <Clapperboard className="w-4 h-4" /> Tạo Video Mới
          </Link>
          <Link
            href="/trends"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-medium"
          >
            <Flame className="w-4 h-4 text-amber-400" /> Quét Xu hướng
          </Link>
        </div>
      </div>

      {error && (
        <div className="bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard
          title="Sản phẩm"
          value={counts?.products ?? "—"}
          sub="Đã xác thực dữ kiện"
          href="/products"
          icon={<FolderKanban className="w-4 h-4 text-emerald-400" />}
        />
        <KpiCard
          title="Footage & Shots"
          value={`${counts?.footage ?? 0} / ${counts?.shots ?? 0}`}
          sub="Video gốc / Cảnh cắt"
          href="/footage"
          icon={<Film className="w-4 h-4 text-sky-400" />}
        />
        <KpiCard
          title="Video Đang Chờ Duyệt"
          value={pendingCount}
          sub={`Tổng đã lập: ${counts?.videos_total ?? 0}`}
          href="/approval"
          icon={<CheckCircle2 className="w-4 h-4 text-amber-400" />}
        />
        <KpiCard
          title="Chi tiêu AI hôm nay"
          value={`$${(data?.ai_budget?.spent_usd ?? 0).toFixed(2)}`}
          sub={`Trần ngày: $${(data?.ai_budget?.limit_usd ?? 5).toFixed(2)}`}
          href="/settings"
          icon={<DollarSign className="w-4 h-4 text-purple-400" />}
        />
      </div>

      {/* Quick Operations Grid */}
      <div className="grid md:grid-cols-3 gap-4">
        <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Flame className="w-4 h-4 text-amber-400" /> Xu hướng & Đề xuất
          </div>
          <p className="text-xs text-slate-400">
            Đã thu thập <strong className="text-slate-200">{counts?.trends ?? 0}</strong> video xu
            hướng và{" "}
            <strong className="text-slate-200">{counts?.suggestions_new ?? 0}</strong> đề xuất chờ
            nhận.
          </p>
          <Link
            href="/trends"
            className="inline-block text-xs text-sky-400 hover:underline font-medium"
          >
            Mở bảng Xu hướng →
          </Link>
        </div>

        <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Sparkles className="w-4 h-4 text-sky-400" /> Video Style & Remotion Studio
          </div>
          <p className="text-xs text-slate-400">
            Tùy chỉnh 6 kiểu phụ đề ASS nhảy chữ, nhạc nền auto-ducking hoặc dựng Remotion tùy biến.
          </p>
          <div className="flex gap-4 text-xs font-medium">
            <Link href="/video-style" className="text-sky-400 hover:underline">
              Quản lý Style →
            </Link>
            <Link href="/studio" className="text-purple-400 hover:underline">
              Mở Studio AI →
            </Link>
          </div>
        </div>

        <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" /> Kênh & Lịch phát hành
          </div>
          <p className="text-xs text-slate-400">
            Đang kết nối <strong className="text-slate-200">{counts?.accounts ?? 0}</strong> kênh •{" "}
            <strong className="text-slate-200">{counts?.posts_scheduled ?? 0}</strong> bài chờ
            đăng • <strong className="text-slate-200">{counts?.posts_posted ?? 0}</strong> đã lên
            sóng.
          </p>
          <Link
            href="/approval"
            className="inline-block text-xs text-sky-400 hover:underline font-medium"
          >
            Duyệt & Lịch đăng →
          </Link>
        </div>
      </div>
    </div>
  );
}

function KpiCard({
  title,
  value,
  sub,
  href,
  icon,
}: {
  title: string;
  value: string | number;
  sub: string;
  href: string;
  icon: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className="bg-[#111827] border border-slate-800 hover:border-slate-700 rounded-xl p-4 transition-colors block"
    >
      <div className="flex items-center justify-between text-xs text-slate-400">
        <span>{title}</span>
        {icon}
      </div>
      <div className="text-2xl font-bold text-white mt-2">{value}</div>
      <div className="text-[11px] text-slate-500 mt-1">{sub}</div>
    </Link>
  );
}
