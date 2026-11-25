"use client";

import React, { useState } from "react";
import { CheckCheck, Share2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import type {
  ApprovalVideo,
  ChannelAccount,
  PerfItem,
  PostItem,
} from "@/app/approval/types";
import { ApprovalQueueGrid } from "@/app/approval/_components/ApprovalQueueGrid";
import { ChannelsAndOAuthPanel } from "@/app/approval/_components/ChannelsAndOAuthPanel";
import { PostsAndPerformancePanel } from "@/app/approval/_components/PostsAndPerformancePanel";
import { PageHeader } from "@/components/vc/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface ApprovalPageBundle {
  pending: ApprovalVideo[];
  accounts: ChannelAccount[];
  posts: PostItem[];
  perf: PerfItem[];
}

export default function ApprovalAndPublishingPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [msg, setMsg] = useState("");

  const { data, error: err, setError: setErr, reload: load } =
    useApiQuery<ApprovalPageBundle>(
      async (signal) => {
        const [aRes, cRes, pRes, mRes] = await Promise.all([
          apiFetch<{ pending: ApprovalVideo[] }>(
            `/api/v1/approvals?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
          apiFetch<{ accounts: ChannelAccount[] }>(
            `/api/v1/accounts?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
          apiFetch<{ posts: PostItem[] }>(
            `/api/v1/posts?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
          apiFetch<{ items: PerfItem[] }>(
            `/api/v1/performance?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
        ]);
        return {
          pending: aRes.pending || [],
          accounts: cRes.accounts || [],
          posts: pRes.posts || [],
          perf: mRes.items || [],
        };
      },
      [activeWorkspaceId],
      { fallbackError: "Lỗi tải dữ liệu duyệt & lịch đăng" }
    );

  const pending = data?.pending || [];
  const accounts = data?.accounts || [];
  const posts = data?.posts || [];
  const perf = data?.perf || [];

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const singleApprove = async (id: number) => {
    setErr("");
    try {
      await apiFetch(`/api/v1/approvals/${id}/approve`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      const m = `Đã duyệt Video #${id}.`;
      setMsg(m);
      toast.success(m);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Duyệt thất bại");
    }
  };

  const singleReject = async (id: number) => {
    await apiFetch(`/api/v1/approvals/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason: "Cần chỉnh sửa lại" }),
    });
    const m = `Đã từ chối Video #${id}.`;
    setMsg(m);
    toast.info(m);
    await load();
  };

  const handleBulkApprove = async () => {
    if (selectedIds.length === 0) return;
    setErr("");
    const res = await apiFetch<{
      approved_ids: number[];
      errors: Record<string, string>;
    }>("/api/v1/approvals/bulk-approve", {
      method: "POST",
      body: JSON.stringify({ video_ids: selectedIds, enforce_policy: true }),
    });
    setSelectedIds([]);
    const errCount = Object.keys(res.errors || {}).length;
    const m =
      `Duyệt hàng loạt: ${res.approved_ids.length} thành công` +
      (errCount > 0
        ? `, ${errCount} bị chặn bởi chính sách strict_footage.`
        : ".");
    setMsg(m);
    toast.success(m);
    await load();
  };

  const retryPost = async (id: number) => {
    await apiFetch(`/api/v1/posts/${id}/retry`, { method: "POST" });
    const m = `Đã xếp lịch đăng lại Bài #${id}.`;
    setMsg(m);
    toast.info(m);
    await load();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        icon={<Share2 className="w-5 h-5" />}
        title="Duyệt bài, Kênh 5 Mạng Xã Hội & Lịch đăng"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {pending.length} chờ duyệt • {posts.length} lịch đăng
          </Badge>
        }
        description="Kiểm duyệt chất lượng từng bài hoặc duyệt hàng loạt, kết nối YouTube, TikTok, Facebook, Instagram, Threads và tải gói xuất bản .zip 5 nền tảng."
        actions={
          selectedIds.length > 0 ? (
            <Button type="button" onClick={() => void handleBulkApprove()}>
              <CheckCheck className="w-4 h-4" /> Duyệt Hàng Loạt (
              {selectedIds.length})
            </Button>
          ) : undefined
        }
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

      <ApprovalQueueGrid
        pending={pending}
        selectedIds={selectedIds}
        onToggleSelect={toggleSelect}
        onToggleSelectAll={() =>
          setSelectedIds(
            selectedIds.length === pending.length ? [] : pending.map((v) => v.id)
          )
        }
        onApprove={singleApprove}
        onReject={singleReject}
      />

      <ChannelsAndOAuthPanel
        workspaceId={activeWorkspaceId}
        accounts={accounts}
        onReload={load}
        onMessage={setMsg}
        onError={setErr}
      />

      <PostsAndPerformancePanel
        posts={posts}
        perf={perf}
        onRetryPost={retryPost}
      />
    </div>
  );
}
