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
import { apiFetch, useWorkspace } from "@/lib/api";

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
  { kind: "render_node", label: "Render MP4" },
  { kind: "publish_node", label: "Gói Đăng Bài" },
];

export default function WorkflowsPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [workflows, setWorkflows] = useState<WorkflowRecord[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [wfName, setWfName] = useState("Workflow Studio mới");
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
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
      setErr(e instanceof Error ? e.message : "Lỗi tải Workflow");
    }
  }, [activeWorkspaceId, selectedId, selectWorkflow]);

  useEffect(() => {
    void load();
  }, [load]);

  const onConnect = useCallback(
    (connection: Connection) => setEdges((eds) => addEdge(connection, eds)),
    [setEdges]
  );

  const addNode = (kind: string, label: string) => {
    const id = `n_${Date.now().toString(36)}`;
    const next: Node = {
      id,
      type: "default",
      position: { x: 120 + (nodes.length % 4) * 210, y: 80 + Math.floor(nodes.length / 4) * 110 },
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
        setMsg(`Đã lưu đồ thị Workflow #${res.workflow.id}.`);
      } else {
        const res = await apiFetch<{ workflow: WorkflowRecord }>("/api/v1/workflows", {
          method: "POST",
          body: JSON.stringify({ workspace_id: activeWorkspaceId, name: wfName, nodes, edges }),
        });
        setSelectedId(res.workflow.id);
        setMsg(`Đã tạo Workflow #${res.workflow.id}.`);
      }
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Đồ thị chứa chu trình hoặc không hợp lệ");
    }
  };

  const runSelected = async () => {
    if (!selectedId) return;
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ job_id: number }>(`/api/v1/workflows/${selectedId}/run`, {
        method: "POST",
        body: JSON.stringify({ workspace_id: activeWorkspaceId, sync: false }),
      });
      setMsg(`Đã xếp hàng chạy DAG Workflow #${selectedId} (Job #${res.job_id}).`);
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể chạy Workflow");
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <WorkflowIcon className="w-6 h-6 text-indigo-400" /> Bảng vẽ Workflow Node (`@xyflow/react`)
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Nối các nút Nhân vật / Sản phẩm / Tin tức → Cảnh → Giọng → Render → Phát hành theo chuẩn DAG.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <button
            type="button"
            onClick={saveWorkflow}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-sky-500 text-slate-950 font-semibold cursor-pointer"
          >
            <Save className="w-3.5 h-3.5" /> Lưu Đồ Thị
          </button>
          <button
            type="button"
            onClick={runSelected}
            disabled={!selectedId}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-500 text-slate-950 font-semibold cursor-pointer disabled:opacity-40"
          >
            <Play className="w-3.5 h-3.5" /> Chạy Workflow
          </button>
          {selectedId && (
            <a
              href={`/api/v1/workflows/${selectedId}/export`}
              download={`workflow_${selectedId}.json`}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-200"
            >
              <Download className="w-3.5 h-3.5" /> Xuất JSON
            </a>
          )}
        </div>
      </div>

      {msg && (
        <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs rounded-lg px-4 py-2.5">
          {msg}
        </div>
      )}
      {err && (
        <div className="bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs rounded-lg px-4 py-2.5">
          {err}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 bg-[#111827] border border-slate-800 rounded-xl p-3 text-xs">
        <select
          value={selectedId ?? ""}
          onChange={(e) => {
            const picked = workflows.find((w) => w.id === Number(e.target.value));
            if (picked) selectWorkflow(picked);
          }}
          className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-1.5"
        >
          {workflows.map((w) => (
            <option key={w.id} value={w.id}>
              {w.is_template ? "[Mẫu] " : ""}{w.name}
            </option>
          ))}
        </select>
        <input
          value={wfName}
          onChange={(e) => setWfName(e.target.value)}
          className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-1.5 flex-1 min-w-[180px]"
        />
        {NODE_PALETTE.map((item) => (
          <button
            key={item.kind}
            type="button"
            onClick={() => addNode(item.kind, item.label)}
            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-sky-300 cursor-pointer"
          >
            <Plus className="w-3 h-3 inline mr-0.5" /> {item.label}
          </button>
        ))}
      </div>

      <div
        className="rounded-xl overflow-hidden border border-slate-800 bg-[#0b0f17]"
        style={{ width: "100%", height: "480px" }}
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

      {workflows.find((w) => w.id === selectedId)?.last_video_id && (
        <div className="text-xs text-slate-300">
          Video gần nhất:{" "}
          <Link
            href={`/videos/${workflows.find((w) => w.id === selectedId)?.last_video_id}`}
            className="text-sky-400 hover:underline"
          >
            Video #{workflows.find((w) => w.id === selectedId)?.last_video_id}
          </Link>
        </div>
      )}
    </div>
  );
}
