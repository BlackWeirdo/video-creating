"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AudioWaveform, Play, Plus, Upload } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, CharacterOption, useWorkspace } from "@/lib/api";
import { JobProgressBanner, useJobProgress } from "@/components/JobProgressBanner";
import { SimulationBadge } from "@/components/SimulationBadge";
import { PageHeader } from "@/components/vc/PageHeader";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  TextareaBox,
  TextInput,
} from "@/components/ui/form-controls";

interface LipsyncProject {
  id: number;
  title: string;
  character_id: number | null;
  portrait_path: string;
  aspect_ratio: string;
  engine_used: string;
  status: string;
  output_path: string;
  video_url: string;
  metrics?: { peak_rms?: number; active_speech_ratio?: number; frames?: number };
  simulation_flags?: string[];
}

export default function LipsyncStudioPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [projects, setProjects] = useState<LipsyncProject[]>([]);
  const [characters, setCharacters] = useState<CharacterOption[]>([]);
  const [title, setTitle] = useState("");
  const [characterId, setCharacterId] = useState("");
  const [aspectRatio, setAspectRatio] = useState("9:16");
  const [scriptText, setScriptText] = useState("");
  const [renderingId, setRenderingId] = useState<number | null>(null);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [lpRes, chRes] = await Promise.all([
        apiFetch<{ projects: LipsyncProject[] }>(
          `/api/v1/lipsync/projects?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ characters: CharacterOption[] }>(
          `/api/v1/characters?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      setProjects(lpRes.projects || []);
      setCharacters(chRes.characters || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Studio Nhép môi");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const { job: activeJob, isRunning: jobRunning } = useJobProgress(activeJobId, {
    onCompleted: () => {
      const done = `Đã xuất xong video chân dung #${renderingId ?? ""}.`;
      setMsg(done);
      toast.success(done);
      setRenderingId(null);
      void load();
    },
    onFailed: (j) => {
      setErr(j.error || "Lỗi dựng chân dung");
      setRenderingId(null);
      void load();
    },
  });

  const createProject = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ project: LipsyncProject }>(
        "/api/v1/lipsync/projects",
        {
          method: "POST",
          body: JSON.stringify({
            workspace_id: activeWorkspaceId,
            title: title || "Chân dung MC Ảo",
            character_id: characterId ? Number(characterId) : null,
            aspect_ratio: aspectRatio,
            script_text: scriptText,
          }),
        }
      );
      setTitle("");
      setScriptText("");
      setMsg(`Đã tạo dự án #${res.project.id}.`);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể tạo dự án");
    }
  };

  const uploadPortrait = async (pid: number, file: File | null) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    await apiFetch(`/api/v1/lipsync/projects/${pid}/upload-portrait`, {
      method: "POST",
      body: fd,
    });
    setMsg(`Đã cập nhật ảnh chân dung cho dự án #${pid}.`);
    await load();
  };

  const renderProject = async (pid: number) => {
    setRenderingId(pid);
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ job_id: number }>(
        `/api/v1/lipsync/projects/${pid}/render`,
        {
          method: "POST",
          body: JSON.stringify({ sync: false }),
        }
      );
      setActiveJobId(res.job_id);
      setMsg(`Đã đưa dự án #${pid} vào hàng đợi xử lý (Tác vụ #${res.job_id}).`);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi xuất video");
      setRenderingId(null);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <PageHeader
        icon={<AudioWaveform className="w-5 h-5" />}
        title="Bản Xem Trước Chân Dung Phát Sóng Âm"
        badges={
          <Badge tone="amber">Tính năng thử nghiệm (Ẩn khỏi menu chính)</Badge>
        }
        description="Kết hợp ảnh chân dung hoặc Nhân vật Cố định với lời thoại lồng tiếng và hiệu ứng sóng âm."
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
        label="Chân dung sóng âm"
        onDismiss={() => setActiveJobId(null)}
      />

      <Card tinted>
        <form onSubmit={createProject} className="space-y-4">
          <SectionHeading>
            <Plus className="w-4 h-4 text-[var(--c-icon)]" /> Tạo Dự Án Mới
          </SectionHeading>

          <div className="grid md:grid-cols-3 gap-3.5">
            <div>
              <FieldLabel htmlFor="lp-title">Tiêu đề dự án *</FieldLabel>
              <TextInput
                id="lp-title"
                required
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
            <div>
              <FieldLabel htmlFor="lp-chr">Nhân vật</FieldLabel>
              <SelectBox
                id="lp-chr"
                value={characterId}
                onChange={(e) => setCharacterId(e.target.value)}
              >
                <option value="">Khung chân dung mặc định</option>
                {characters.map((ch) => (
                  <option key={ch.id} value={ch.id}>
                    {ch.name}
                  </option>
                ))}
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="lp-ratio">Tỷ lệ khung hình</FieldLabel>
              <SelectBox
                id="lp-ratio"
                value={aspectRatio}
                onChange={(e) => setAspectRatio(e.target.value)}
              >
                <option value="9:16">9:16 Dọc</option>
                <option value="16:9">16:9 Ngang</option>
                <option value="1:1">1:1 Vuông</option>
              </SelectBox>
            </div>
          </div>

          <div>
            <FieldLabel htmlFor="lp-script">Lời thoại MC *</FieldLabel>
            <TextareaBox
              id="lp-script"
              required
              rows={3}
              value={scriptText}
              onChange={(e) => setScriptText(e.target.value)}
            />
          </div>

          <Button type="submit">Tạo Dự Án</Button>
        </form>
      </Card>

      {projects.length === 0 ? (
        <EmptyState title="Chưa có dự án nào" />
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {projects.map((p) => (
            <Card key={p.id} className="space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-[14.5px] font-bold text-[var(--text-primary)]">
                    {p.title}
                  </div>
                  <div className="text-[12px] text-[var(--text-muted)]">
                    {p.engine_used} • {p.aspect_ratio} • {p.status}
                  </div>
                </div>
                <div className="flex gap-1.5">
                  <label className="inline-flex min-h-[34px] items-center gap-1 rounded-[8px] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-2.5 py-1 text-[12.5px] font-semibold text-[var(--text-primary)] cursor-pointer">
                    <Upload className="w-3.5 h-3.5" /> Ảnh
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      className="sr-only"
                      onChange={(e) =>
                        void uploadPortrait(p.id, e.target.files?.[0] || null)
                      }
                    />
                  </label>
                  <Button
                    type="button"
                    size="sm"
                    variant="emerald"
                    disabled={jobRunning && renderingId === p.id}
                    onClick={() => void renderProject(p.id)}
                  >
                    <Play className="w-3.5 h-3.5" /> Xuất
                  </Button>
                </div>
              </div>
              {p.video_url && (
                <video
                  controls
                  preload="metadata"
                  src={p.video_url}
                  className="w-full max-h-56 rounded-[9px] bg-black"
                />
              )}
              <SimulationBadge flags={p.simulation_flags} />
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
