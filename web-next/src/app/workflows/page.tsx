"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  addEdge,
  Background,
  Controls,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Download, Play, Plus, Save, Workflow as WorkflowIcon } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { JobProgressBanner, useJobProgress } from "@/components/JobProgressBanner";
import { PageHeader } from "@/components/vc/PageHeader";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SelectBox, TextInput } from "@/components/ui/form-controls";

interface WorkflowRecord {
  id: number;
  name: string;
  description: string;
  nodes: Node[];
  edges: Edge[];
  is_template: boolean;
  last_status: string;
  last_video_id: number | null;
}

const NODE_PALETTE = [
  { kind: "character_node", label: "Nhân vật AI" },
  { kind: "product_node", label: "Sản phẩm" },
  { kind: "news_node", label: "Tin tức" },
  { kind: "scene_node", label: "Cảnh & Kịch bản" },
  { kind: "voice_node", label: "Giọng đọc TTS" },
  { kind: "render_node", label: "Xuất MP4" },
  { kind: "publish_node", label: "Gói Đăng Bài" },
];

export default function WorkflowsPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [workflows, setWorkflows] = useState<WorkflowRecord[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [wfName, setWfName] = useState("Quy trình tự động mới");
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const selectWorkflow = useCallback(
    (wf: WorkflowRecord) => {
      setSelectedId(wf.id);
      setWfName(wf.name);
      setNodes(wf.nodes || []);
      setEdges(wf.edges || []);
    },
    [setEdges, setNodes]
  );

  const load = useCallback(async () => {
    try {
      const res = await apiFetch<{ workflows: WorkflowRecord[] }>(
        `/api/v1/workflows?workspace_id=${activeWorkspaceId}`
      );
      const list = res.workflows || [];
      setWorkflows(list);
      if (list.length > 0 && selectedId === null) {
        selectWorkflow(list[0]);
      }
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Quy trình tự động");
    }
  }, [activeWorkspaceId, selectedId, selectWorkflow]);

  useEffect(() => {
    void load();
  }, [load]);

  const { job: activeJob } = useJobProgress(activeJobId, {
    onCompleted: () => {
      setMsg("Đã chạy xong đồ thị quy trình tự động!");
      toast.success("Hoàn tất chạy quy trình tự động!");
      void load();
    },
    onFailed: (j) => {
      setErr(j.error || "Quy trình gặp lỗi");
      void load();
    },
  });

  const onConnect = useCallback(
    (connection: Connection) => setEdges((eds) => addEdge(connection, eds)),
    [setEdges]
  );

  const addNode = (kind: string, label: string) => {
    const id = `n_${Date.now().toString(36)}`;
    const next: Node = {
      id,
      type: "default",
      position: {
        x: 120 + (nodes.length % 4) * 210,
        y: 80 + Math.floor(nodes.length / 4) * 110,
      },
      data: { label, node_kind: kind },
    };
    setNodes((prev) => [...prev, next]);
  };

  const saveWorkflow = async () => {
    setErr("");
    setMsg("");
    try {
      if (selectedId) {
        const res = await apiFetch<{ workflow: WorkflowRecord }>(
          `/api/v1/workflows/${selectedId}`,
          {
            method: "PATCH",
            body: JSON.stringify({ name: wfName, nodes, edges }),
          }
        );
        const m = `Đã lưu đồ thị quy trình #${res.workflow.id}.`;
        setMsg(m);
        toast.success(m);
      } else {
        const res = await apiFetch<{ workflow: WorkflowRecord }>(
          "/api/v1/workflows",
          {
            method: "POST",
            body: JSON.stringify({
              workspace_id: activeWorkspaceId,
              name: wfName,
              nodes,
              edges,
            }),
          }
        );
        setSelectedId(res.workflow.id);
        const m = `Đã tạo quy trình #${res.workflow.id}.`;
        setMsg(m);
        toast.success(m);
      }
      await load();
    } catch (e2) {
      setErr(
        e2 instanceof Error
          ? e2.message
          : "Đồ thị chứa chu trình lặp hoặc không hợp lệ"
      );
    }
  };

  const runSelected = async () => {
    if (!selectedId) return;
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ job_id: number }>(
        `/api/v1/workflows/${selectedId}/run`,
        {
          method: "POST",
          body: JSON.stringify({ workspace_id: activeWorkspaceId, sync: false }),
        }
      );
      setActiveJobId(res.job_id);
      const m = `Đã đưa quy trình #${selectedId} vào hàng đợi xử lý (Tác vụ #${res.job_id}).`;
      setMsg(m);
      toast.info(m);
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể chạy quy trình");
    }
  };

  const latestVideoId = workflows.find((w) => w.id === selectedId)?.last_video_id;

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      <PageHeader
        icon={<WorkflowIcon className="w-5 h-5" />}
        title="Quy Trình Tự Động Kéo Thả (Workflow)"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {workflows.length} quy trình
          </Badge>
        }
        description="Kết nối trực quan các khối Nhân vật / Sản phẩm / Tin tức → Cảnh → Giọng đọc → Xuất MP4 → Đóng gói đăng bài."
        actions={
          <>
            <Button type="button" variant="secondary" onClick={() => void saveWorkflow()}>
              <Save className="w-4 h-4" /> Lưu Đồ Thị
            </Button>
            {selectedId && (
              <Button asChild variant="secondary">
                <a
                  href={`/api/v1/workflows/${selectedId}/export`}
                  download={`workflow_${selectedId}.json`}
                >
                  <Download className="w-4 h-4" /> Xuất JSON
                </a>
              </Button>
            )}
            <Button
              type="button"
              disabled={!selectedId}
              onClick={() => void runSelected()}
            >
              <Play className="w-4 h-4" /> Chạy Quy Trình
            </Button>
          </>
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

      <JobProgressBanner
        job={activeJob}
        jobId={activeJobId}
        label="Quy trình tự động"
        onDismiss={() => setActiveJobId(null)}
      />

      <Card className="space-y-3 p-3.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <SelectBox
            aria-label="Chọn quy trình có sẵn"
            value={selectedId ?? ""}
            onChange={(e) => {
              const picked = workflows.find(
                (w) => w.id === Number(e.target.value)
              );
              if (picked) selectWorkflow(picked);
            }}
            className="sm:w-64"
          >
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.is_template ? "[Mẫu] " : ""}
                {w.name}
              </option>
            ))}
          </SelectBox>

          <TextInput
            aria-label="Tên quy trình"
            value={wfName}
            onChange={(e) => setWfName(e.target.value)}
            className="flex-1 min-w-[200px]"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12px] font-medium text-[var(--text-muted)]">
            Thêm nút vào bảng vẽ:
          </span>
          {NODE_PALETTE.map((item) => (
            <Button
              key={item.kind}
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => addNode(item.kind, item.label)}
            >
              <Plus className="w-3.5 h-3.5 text-[var(--c-icon)]" /> {item.label}
            </Button>
          ))}
        </div>
      </Card>

      <div
        className="rounded-[14px] overflow-hidden border border-[var(--border-strong)] bg-[var(--bg-card)] shadow-[var(--shadow-sm)]"
        style={{ width: "100%", height: "490px" }}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          fitView
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>

      {latestVideoId && (
        <div className="text-[13px] text-[var(--text-secondary)]">
          Video xuất gần nhất:{" "}
          <Link
            href={`/videos/${latestVideoId}`}
            className="font-semibold text-[var(--c-tx)] hover:underline"
          >
            Mở Video #{latestVideoId} →
          </Link>
        </div>
      )}
    </div>
  );
}
