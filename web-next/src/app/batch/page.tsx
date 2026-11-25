"use client";

import React, { useState } from "react";
import { Layers } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import type { BatchRunRow, ProductOption } from "@/app/batch/types";
import { CreateBatchCard } from "@/app/batch/_components/CreateBatchCard";
import { BatchHistoryAndVariants } from "@/app/batch/_components/BatchHistoryAndVariants";
import { JobProgressBanner, useJobProgress } from "@/components/JobProgressBanner";
import { PageHeader } from "@/components/vc/PageHeader";
import { Badge } from "@/components/ui/badge";

interface BatchPageBundle {
  batches: BatchRunRow[];
  products: ProductOption[];
  firstDetail: BatchRunRow | null;
}

export default function BatchStudioPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [selectedBatch, setSelectedBatch] = useState<BatchRunRow | null>(null);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");

  const { data, error: err, setError: setErr, reload: load } =
    useApiQuery<BatchPageBundle>(
      async (signal) => {
        const [bRes, pRes] = await Promise.all([
          apiFetch<{ batches: BatchRunRow[] }>(
            `/api/v1/batches?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
          apiFetch<{ products: ProductOption[] }>(
            `/api/v1/products?workspace_id=${activeWorkspaceId}`,
            { signal }
          ),
        ]);
        const list = bRes.batches || [];
        let firstDetail: BatchRunRow | null = null;
        if (list.length > 0) {
          const detail = await apiFetch<{ batch: BatchRunRow }>(
            `/api/v1/batches/${list[0].id}`,
            { signal }
          );
          firstDetail = detail.batch;
        }
        return {
          batches: list,
          products: pRes.products || [],
          firstDetail,
        };
      },
      [activeWorkspaceId],
      {
        fallbackError: "Lỗi tải Sản xuất hàng loạt",
        onSuccess: (bundle) => {
          setSelectedBatch(bundle.firstDetail);
        },
      }
    );

  const batches = data?.batches || [];
  const products = data?.products || [];

  const { job: activeJob } = useJobProgress(activeJobId, {
    onStepChange: () => {
      void load();
    },
    onCompleted: () => {
      setMsg("Đã hoàn tất chạy lô sản xuất hàng loạt (A/B)!");
      toast.success("Hoàn tất lô sản xuất hàng loạt!");
      void load();
    },
    onFailed: (j) => {
      setErr(j.error || "Lô sản xuất gặp lỗi");
      void load();
    },
  });

  const inspectBatch = async (id: number) => {
    const detail = await apiFetch<{ batch: BatchRunRow }>(`/api/v1/batches/${id}`);
    setSelectedBatch(detail.batch);
  };

  const retryFailed = async (id: number) => {
    const res = await apiFetch<{ job_id: number }>(`/api/v1/batches/${id}/retry`, {
      method: "POST",
      body: JSON.stringify({ failed_only: true, sync: false }),
    });
    setActiveJobId(res.job_id);
    const m = `Đã chạy lại các mục lỗi từ điểm lưu của lô #${id} (Tác vụ #${res.job_id}).`;
    setMsg(m);
    toast.info(m);
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        icon={<Layers className="w-5 h-5" />}
        title="Sản Xuất Hàng Loạt & Biến Thể A/B"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {batches.length} chiến dịch
          </Badge>
        }
        description="Tự động nhân bản 1–3 biến thể góc mở đầu (Hook) và kiểu phụ đề A/B/C cho nhiều sản phẩm cùng lúc, hỗ trợ chạy lại đúng bước bị lỗi."
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

      <JobProgressBanner
        job={activeJob}
        jobId={activeJobId}
        label="Sản xuất hàng loạt"
        onDismiss={() => setActiveJobId(null)}
      />

      <CreateBatchCard
        workspaceId={activeWorkspaceId}
        products={products}
        onCreated={async (jid) => {
          setActiveJobId(jid);
          await load();
        }}
        onMessage={setMsg}
        onError={setErr}
      />

      <BatchHistoryAndVariants
        batches={batches}
        activeBatch={selectedBatch}
        onSelectBatch={inspectBatch}
        onRetryFailed={retryFailed}
      />
    </div>
  );
}
