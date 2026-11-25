"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Eye, Languages, Play, Plus, Scissors } from "lucide-react";
import { JobProgressBanner } from "@/components/JobProgressBanner";
import { SimulationBadge } from "@/components/SimulationBadge";
import { PageHeader, PipelineStepItem } from "@/components/vc/PageHeader";
import { PolicyBadge } from "@/components/vc/PolicyBadge";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useLocalizeProject } from "@/app/localize/useLocalizeProject";
import { CreateLocalizeForm } from "@/app/localize/CreateLocalizeForm";
import {
  HardsubBoxPreview,
  SpeakerVoicePanel,
} from "@/app/localize/SpeakerVoicePanel";
import {
  BilingualSegmentsTable,
  VoiceCloneConsentModal,
} from "@/app/localize/BilingualSegmentsTable";

const MODE_LABELS: Record<string, string> = {
  reup_vi: "Việt hóa Full AI",
  hybrid_remix: "Hybrid Remix",
  intl_export: "Quốc tế hóa",
};

export default function LocalizePage() {
  const {
    activeWorkspaceId,
    wsPolicy,
    canCloneVoice,
    projects,
    shots,
    setSelectedId,
    activeProj,
    previewAudioMap,
    previewLoadingKey,
    showBoxPreview,
    setShowBoxPreview,
    cloneModalOpen,
    setCloneModalOpen,
    activeJobId,
    setActiveJobId,
    activeJob,
    msg,
    setMsg,
    err,
    setErr,
    load,
    runAction,
    updateSegField,
    updateSpeakerConfig,
    updateHardsubBox,
    handlePreviewLine,
    toggleCloneVoice,
    confirmEnableClone,
  } = useLocalizeProject();

  const [showCreateForm, setShowCreateForm] = useState(projects.length === 0);

  const hasExtracted = Boolean(activeProj && activeProj.segments.length > 0);
  const hasRendered = Boolean(activeProj?.output_video_id);
  const steps: PipelineStepItem[] = [
    {
      title: "1. Tách nhạc nền",
      subtitle: "MDX-Net sạch lời",
      state: hasExtracted ? "done" : activeProj ? "active" : "idle",
    },
    {
      title: "2. Quét chữ & Lời",
      subtitle: "RapidOCR + Whisper",
      state: hasExtracted ? "done" : "idle",
    },
    {
      title: "3. Dịch khớp nhịp",
      subtitle: "Biên tập song ngữ",
      state: hasRendered ? "done" : hasExtracted ? "active" : "idle",
    },
    {
      title: "4. Phân vai giọng",
      subtitle: "Edge TTS / VieNeu",
      state: hasRendered ? "done" : hasExtracted ? "active" : "idle",
    },
    {
      title: "5. Xuất Master",
      subtitle: "Karaoke • -14 LUFS",
      state: hasRendered ? "done" : "idle",
    },
  ];

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      <PageHeader
        icon={<Languages className="w-5 h-5" />}
        title="Việt hóa, Hybrid Remix & Quốc tế hóa"
        badges={<PolicyBadge policy={wsPolicy} showDetail />}
        description="Tách nhạc nền MDX-Net ONNX, quét chữ cứng Trung/Anh kết hợp Faster-Whisper, phân vai nhiều người nói và nhân bản giọng VieNeu CPU."
        steps={steps}
        actions={
          <>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setShowCreateForm((v) => !v)}
            >
              <Plus className="w-4 h-4" />
              {showCreateForm ? "Ẩn biểu mẫu tạo" : "Dự án mới"}
            </Button>
            {activeProj && (
              <Button
                type="button"
                onClick={() => void runAction(activeProj.id, "render")}
              >
                <Play className="w-4 h-4" /> Xuất Video Master (#{activeProj.id})
              </Button>
            )}
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
        label="Studio Việt hóa"
        onDismiss={() => setActiveJobId(null)}
      />

      {(showCreateForm || projects.length === 0) && (
        <CreateLocalizeForm
          workspaceId={activeWorkspaceId}
          wsPolicy={wsPolicy}
          onCreated={async (newId) => {
            setSelectedId(newId);
            setShowCreateForm(false);
            await load();
          }}
          onError={setErr}
          onMessage={setMsg}
        />
      )}

      <div className="grid lg:grid-cols-3 gap-4 items-start">
        {/* Left: Project List */}
        <Card className="space-y-3">
          <CardTitleRow>
            <SectionHeading className="tabular-nums">
              Danh sách dự án ({projects.length})
            </SectionHeading>
            <Badge tone="cluster" className="tabular-nums">
              {projects.length} dự án
            </Badge>
          </CardTitleRow>

          {projects.length === 0 ? (
            <EmptyState
              title="Chưa có dự án Việt hóa nào"
              description="Tải lên một video nguồn ở biểu mẫu phía trên để bắt đầu tách lời và dịch."
            />
          ) : (
            <div className="space-y-2.5">
              {projects.map((p) => {
                const isSelected = activeProj?.id === p.id;
                return (
                  <div
                    key={p.id}
                    onClick={() => setSelectedId(p.id)}
                    className={`rounded-[11px] border p-3 cursor-pointer space-y-2 transition-colors ${
                      isSelected
                        ? "bg-[var(--c-soft)] border-[var(--c-bd)]"
                        : "bg-[var(--bg-elevated)] border-[var(--border-subtle)] hover:border-[var(--c-bd)]"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-[13.5px] font-semibold text-[var(--text-primary)]">
                        #{p.id} • {p.title}
                      </span>
                      <Badge
                        tone={
                          p.status === "rendered" || p.status === "ready"
                            ? "emerald"
                            : p.status === "failed"
                              ? "rose"
                              : "sky"
                        }
                      >
                        {p.status}
                      </Badge>
                    </div>
                    <div className="text-[12px] text-[var(--text-muted)]">
                      {MODE_LABELS[p.mode] || p.mode} → {p.target_lang} •{" "}
                      {p.translation_style === "literal"
                        ? "Sát nghĩa"
                        : "Tự nhiên"}
                    </div>
                    <div className="flex flex-wrap items-center gap-2 pt-0.5">
                      <Button
                        type="button"
                        size="sm"
                        variant="amber"
                        onClick={(ev) => {
                          ev.stopPropagation();
                          void runAction(p.id, "extract");
                        }}
                      >
                        <Scissors className="w-3.5 h-3.5" /> Tách lời &amp; Dịch
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="emerald"
                        onClick={(ev) => {
                          ev.stopPropagation();
                          void runAction(p.id, "render");
                        }}
                      >
                        <Play className="w-3.5 h-3.5" /> Xuất video
                      </Button>
                      {p.output_video_id && (
                        <Link
                          href={`/videos/${p.output_video_id}`}
                          onClick={(ev) => ev.stopPropagation()}
                          className="text-[12.5px] font-semibold text-[var(--c-tx)] hover:underline"
                        >
                          Video #{p.output_video_id} →
                        </Link>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        {/* Right: Bilingual Segments + Speaker Voice Panel */}
        <Card tinted className="lg:col-span-2 space-y-4">
          <CardTitleRow>
            <SectionHeading>
              Bảng Song Ngữ &amp; Phân Vai Giọng Đọc
              {activeProj ? ` — #${activeProj.id}` : ""}
            </SectionHeading>
            {activeProj && (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={() => setShowBoxPreview((v) => !v)}
              >
                <Eye className="w-3.5 h-3.5 text-[var(--c-icon)]" />
                {showBoxPreview
                  ? "Ẩn vùng che chữ"
                  : `Vùng che chữ cứng (${activeProj.ocr_cues?.length || 0} mốc OCR)`}
              </Button>
            )}
          </CardTitleRow>

          {activeProj && <SimulationBadge flags={activeProj.simulation_flags} />}

          {activeProj && activeProj.segments.length > 0 && (
            <SpeakerVoicePanel
              project={activeProj}
              canCloneVoice={canCloneVoice}
              onUpdateSpeaker={(spkId, patch) =>
                updateSpeakerConfig(activeProj, spkId, patch)
              }
              onToggleClone={(want) => toggleCloneVoice(activeProj, want)}
            />
          )}

          {activeProj && showBoxPreview && (
            <HardsubBoxPreview
              project={activeProj}
              onUpdateBox={(k, val) => updateHardsubBox(activeProj, k, val)}
            />
          )}

          <BilingualSegmentsTable
            project={activeProj}
            shots={shots}
            previewAudioMap={previewAudioMap}
            previewLoadingKey={previewLoadingKey}
            onUpdateSegment={(idx, patch) =>
              activeProj ? updateSegField(activeProj, idx, patch) : Promise.resolve()
            }
            onPreviewLine={(idx) =>
              activeProj ? handlePreviewLine(activeProj, idx) : Promise.resolve()
            }
          />
        </Card>
      </div>

      <VoiceCloneConsentModal
        open={cloneModalOpen}
        projectId={activeProj?.id ?? null}
        onOpenChange={setCloneModalOpen}
        onConfirm={confirmEnableClone}
      />
    </div>
  );
}
