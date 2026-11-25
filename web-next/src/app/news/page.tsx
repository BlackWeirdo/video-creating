"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Download, Newspaper, Play, Plus, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import { JobProgressBanner, useJobProgress } from "@/components/JobProgressBanner";
import { SimulationBadge } from "@/components/SimulationBadge";
import { PageHeader } from "@/components/vc/PageHeader";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  TextareaBox,
  TextInput,
} from "@/components/ui/form-controls";

interface NewsProject {
  id: number;
  title: string;
  source_kind: string;
  source_url: string;
  status: string;
  output_video_id: number | null;
  publish_pack_path: string;
  facts?: { headline?: string; preserved_tokens?: string[] };
  script?: Array<{ role: string; duration_s: number; text: string }>;
  simulation_flags?: string[];
}

export default function NewsPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [sourceKind, setSourceKind] = useState<"url" | "rss" | "raw_text">(
    "raw_text"
  );
  const [title, setTitle] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [rawText, setRawText] = useState("");
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");

  const { data, error: err, setError: setErr, reload: load } = useApiQuery<
    NewsProject[]
  >(
    async (signal) => {
      const res = await apiFetch<{ projects: NewsProject[] }>(
        `/api/v1/news/projects?workspace_id=${activeWorkspaceId}`,
        { signal }
      );
      return res.projects || [];
    },
    [activeWorkspaceId],
    { fallbackError: "Lỗi tải Studio Tin tức" }
  );

  const projects = data || [];

  const { job: activeJob } = useJobProgress(activeJobId, {
    onCompleted: () => {
      const done = "Đã xuất xong video Bản tin & gói đăng bài .zip!";
      setMsg(done);
      toast.success(done);
      void load();
    },
    onFailed: (j) => {
      setErr(j.error || "Lỗi xuất Bản tin");
      void load();
    },
  });

  const createNews = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ project: NewsProject }>(
        "/api/v1/news/projects",
        {
          method: "POST",
          body: JSON.stringify({
            workspace_id: activeWorkspaceId,
            title,
            source_kind: sourceKind,
            source_url: sourceUrl,
            raw_text: rawText,
          }),
        }
      );
      setTitle("");
      setSourceUrl("");
      setRawText("");
      const m = `Đã tạo dự án Bản tin #${res.project.id}.`;
      setMsg(m);
      toast.success(m);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không tạo được bản tin");
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <PageHeader
        icon={<Newspaper className="w-5 h-5" />}
        title="Tin Tức & Bài Viết → Video Bản Tin"
        badges={
          <Badge tone="cluster" className="tabular-nums">
            {projects.length} bản tin
          </Badge>
        }
        description="Nạp bài báo từ liên kết URL, nguồn RSS hoặc văn bản thô; tự động khóa bảo toàn con số thực tế và xuất video kèm gói đăng bài .zip."
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
        label="Studio Tin tức"
        onDismiss={() => setActiveJobId(null)}
      />

      <Card tinted>
        <form onSubmit={createNews} className="space-y-4">
          <SectionHeading>
            <Plus className="w-4 h-4 text-[var(--c-icon)]" /> Tạo Bản Tin Mới
          </SectionHeading>

          <div className="grid md:grid-cols-3 gap-3.5">
            <div>
              <FieldLabel htmlFor="nw-title">Tiêu đề bản tin</FieldLabel>
              <TextInput
                id="nw-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="VD: Điểm tin thị trường vàng bạc sáng nay"
              />
            </div>
            <div>
              <FieldLabel htmlFor="nw-kind">Nguồn nội dung</FieldLabel>
              <SelectBox
                id="nw-kind"
                value={sourceKind}
                onChange={(e) =>
                  setSourceKind(e.target.value as "url" | "rss" | "raw_text")
                }
              >
                <option value="raw_text">Dán trực tiếp nội dung bài viết</option>
                <option value="url">Đọc từ liên kết bài báo</option>
                <option value="rss">Đọc từ nguồn RSS</option>
              </SelectBox>
            </div>
            {sourceKind !== "raw_text" && (
              <div>
                <FieldLabel htmlFor="nw-url">Địa chỉ URL / RSS *</FieldLabel>
                <TextInput
                  id="nw-url"
                  required
                  value={sourceUrl}
                  onChange={(e) => setSourceUrl(e.target.value)}
                  placeholder="https://..."
                />
              </div>
            )}
          </div>

          {sourceKind === "raw_text" && (
            <div>
              <FieldLabel htmlFor="nw-raw">
                Nội dung bài viết * (các con số quan trọng sẽ được bảo toàn)
              </FieldLabel>
              <TextareaBox
                id="nw-raw"
                required
                rows={4}
                value={rawText}
                onChange={(e) => setRawText(e.target.value)}
                placeholder="Dán nội dung tin tức vào đây..."
              />
            </div>
          )}

          <Button type="submit">Tạo Bản Tin</Button>
        </form>
      </Card>

      {projects.length === 0 ? (
        <EmptyState
          icon={<Newspaper className="w-5 h-5" />}
          title="Chưa có dự án bản tin nào"
          description="Tạo bản tin mới ở biểu mẫu phía trên để tóm tắt kịch bản và dựng video."
        />
      ) : (
        <div className="space-y-3.5">
          {projects.map((p) => (
            <Card key={p.id} className="space-y-3">
              <CardTitleRow>
                <div className="flex flex-wrap items-center gap-2">
                  <strong className="text-[15px] text-[var(--text-primary)]">
                    #{p.id} — {p.title}
                  </strong>
                  <Badge tone="sky">{p.source_kind}</Badge>
                  <Badge tone="neutral">{p.status}</Badge>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="amber"
                    onClick={async () => {
                      await apiFetch(`/api/v1/news/projects/${p.id}/summarize`, {
                        method: "POST",
                      });
                      const m = `Đã trích số liệu & tóm tắt kịch bản cho Bản tin #${p.id}.`;
                      setMsg(m);
                      toast.success(m);
                      await load();
                    }}
                  >
                    <Sparkles className="w-3.5 h-3.5" /> Tóm tắt &amp; Giữ số liệu
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="emerald"
                    onClick={async () => {
                      const res = await apiFetch<{ job_id: number }>(
                        `/api/v1/news/projects/${p.id}/render`,
                        {
                          method: "POST",
                          body: JSON.stringify({ sync: false, build_pack: true }),
                        }
                      );
                      setActiveJobId(res.job_id);
                      const m = `Đã đưa Bản tin #${p.id} vào hàng đợi xuất video (Tác vụ #${res.job_id}).`;
                      setMsg(m);
                      toast.info(m);
                    }}
                  >
                    <Play className="w-3.5 h-3.5" /> Xuất MP4 + Gói .zip
                  </Button>
                </div>
              </CardTitleRow>

              {p.facts?.preserved_tokens && p.facts.preserved_tokens.length > 0 && (
                <div className="text-[12.5px] font-medium text-[var(--st-amber-tx)]">
                  Số liệu được khóa bảo toàn:{" "}
                  {p.facts.preserved_tokens.join(" • ")}
                </div>
              )}

              {p.script && p.script.length > 0 && (
                <div className="grid md:grid-cols-3 gap-2.5">
                  {p.script.map((s, idx) => (
                    <div
                      key={idx}
                      className="rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 text-[12.5px]"
                    >
                      <div className="text-[11px] font-bold uppercase text-[var(--c-tx)] mb-1">
                        {s.role}
                      </div>
                      <div className="text-[var(--text-secondary)]">{s.text}</div>
                    </div>
                  ))}
                </div>
              )}

              <SimulationBadge flags={p.simulation_flags} />

              <div className="flex flex-wrap gap-3 text-[13px]">
                {p.output_video_id && (
                  <Link
                    href={`/videos/${p.output_video_id}`}
                    className="font-semibold text-[var(--c-tx)] hover:underline"
                  >
                    Xem Video #{p.output_video_id} →
                  </Link>
                )}
                {p.publish_pack_path && (
                  <a
                    href={`/files/${p.publish_pack_path}`}
                    className="inline-flex items-center gap-1 font-semibold text-[var(--st-emerald-tx)] hover:underline"
                  >
                    <Download className="w-3.5 h-3.5" /> Tải Gói Đăng Bài (.zip)
                  </a>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
