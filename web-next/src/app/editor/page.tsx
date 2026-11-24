"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Film, Play, Plus, Scissors, Trash2 } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";
import { JobProgressBanner, useJobProgress } from "@/components/JobProgressBanner";

interface MediaClip {
  id: number;
  url: string;
  output_path?: string;
  media_path?: string;
  duration_s?: number;
  description?: string;
}

interface TimelineClip {
  source_path: string;
  start_s: number;
  duration_s: number;
}

interface EditorProject {
  id: number;
  title: string;
  status: string;
  output_video_id: number | null;
  tracks: {
    video_clips: TimelineClip[];
    subtitles: Array<{ start_s: number; end_s: number; text: string }>;
  };
}

export default function EditorPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [tab, setTab] = useState<"freecut" | "timeline">("freecut");
  const [videos, setVideos] = useState<MediaClip[]>([]);
  const [shots, setShots] = useState<MediaClip[]>([]);
  const [selectedJob, setSelectedJob] = useState<string>("");
  const [projects, setProjects] = useState<EditorProject[]>([]);
  const [clips, setClips] = useState<TimelineClip[]>([]);
  const [subText, setSubText] = useState("Tiêu đề Timeline Editor");
  const [projTitle, setProjTitle] = useState("Bản dựng Đa track mới");
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [mRes, pRes] = await Promise.all([
        apiFetch<{ videos: MediaClip[]; shots: MediaClip[] }>(
          `/api/v1/editor/media?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ projects: EditorProject[] }>(
          `/api/v1/editor/projects?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      const vids = mRes.videos || [];
      setVideos(vids);
      setShots(mRes.shots || []);
      setProjects(pRes.projects || []);
      if (vids.length > 0 && !selectedJob) {
        setSelectedJob(String(vids[0].id));
      }
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Trình dựng");
    }
  }, [activeWorkspaceId, selectedJob]);

  useEffect(() => {
    void load();
  }, [load]);

  const { job: activeJob, isRunning: jobRunning } = useJobProgress(activeJobId, {
    onCompleted: () => {
      setMsg("Đã xuất xong video Timeline Đa track!");
      void load();
    },
    onFailed: (j) => {
      setErr(j.error || "Lỗi render Timeline");
      void load();
    },
  });

  const renderTimeline = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const cr = await apiFetch<{ project: EditorProject }>("/api/v1/editor/projects", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          title: projTitle,
          tracks: {
            video_clips: clips,
            audio_clips: [],
            subtitles: subText.trim()
              ? [{ start_s: 0.1, end_s: Math.max(2.0, clips.reduce((s, c) => s + c.duration_s, 0) - 0.1), text: subText }]
              : [],
          },
        }),
      });
      const rn = await apiFetch<{ job_id: number }>(
        `/api/v1/editor/projects/${cr.project.id}/render`,
        { method: "POST", body: JSON.stringify({ style_preset: "tiktok_karaoke", sync: false }) }
      );
      setActiveJobId(rn.job_id);
      setMsg(`Đã xếp hàng xuất video Timeline #${cr.project.id} (Job #${rn.job_id}).`);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi render Timeline");
    }
  };

  const freecutUrl = selectedJob ? `/freecut/?job=${encodeURIComponent(selectedJob)}` : "/freecut/";

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Scissors className="w-6 h-6 text-rose-400" /> Trình dựng Timeline FreeCut (MIT)
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Chỉnh sửa từng khung hình bằng FreeCut nhúng (`/api/editor/*`) hoặc ghép Đa track ngay trên máy chủ.
          </p>
        </div>
        <div className="flex gap-2 text-xs">
          <button
            type="button"
            onClick={() => setTab("freecut")}
            className={`px-3 py-1.5 rounded-lg border cursor-pointer ${
              tab === "freecut"
                ? "bg-sky-500 text-slate-950 border-sky-400 font-semibold"
                : "bg-[#111827] border-slate-700 text-slate-300"
            }`}
          >
            FreeCut Studio (Nhúng)
          </button>
          <button
            type="button"
            onClick={() => setTab("timeline")}
            className={`px-3 py-1.5 rounded-lg border cursor-pointer ${
              tab === "timeline"
                ? "bg-sky-500 text-slate-950 border-sky-400 font-semibold"
                : "bg-[#111827] border-slate-700 text-slate-300"
            }`}
          >
            Ghép Đa Track FFmpeg ({projects.length})
          </button>
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
      <JobProgressBanner
        job={activeJob}
        jobId={activeJobId}
        label="Timeline FFmpeg"
        onDismiss={() => setActiveJobId(null)}
      />

      {tab === "freecut" ? (
        <div className="space-y-3 text-xs">
          <div className="flex items-center gap-3 bg-[#111827] border border-slate-800 rounded-xl p-3">
            <span className="text-slate-300">Mở Video trong FreeCut:</span>
            <select
              value={selectedJob}
              onChange={(e) => setSelectedJob(e.target.value)}
              className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-1.5"
            >
              <option value="">-- Trình dựng trống --</option>
              {videos.map((v) => (
                <option key={v.id} value={String(v.id)}>
                  Video #{v.id} ({v.duration_s ? `${v.duration_s}s` : "—"})
                </option>
              ))}
            </select>
            <a href={freecutUrl} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline ml-auto">
              Mở toàn màn hình ↗
            </a>
          </div>
          <div className="rounded-xl overflow-hidden border border-slate-800 bg-black h-[640px]">
            <iframe src={freecutUrl} title="FreeCut Studio" className="w-full h-full border-0" />
          </div>
        </div>
      ) : (
        <div className="grid lg:grid-cols-2 gap-4 text-xs">
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3">
            <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
              <Film className="w-4 h-4 text-sky-400" /> Kho Shot &amp; Video Workspace
            </h2>
            <div className="space-y-1.5 max-h-64 overflow-y-auto">
              {shots.map((s) => (
                <div
                  key={`s-${s.id}`}
                  className="flex justify-between items-center bg-[#182235] rounded px-3 py-2"
                >
                  <span>
                    Shot #{s.id} — {s.description || "Clip"}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setClips((prev) => [
                        ...prev,
                        { source_path: s.media_path || "", start_s: 0, duration_s: 2.5 },
                      ])
                    }
                    className="px-2 py-1 rounded bg-sky-500/20 text-sky-300 cursor-pointer"
                  >
                    <Plus className="w-3 h-3 inline" /> Thêm
                  </button>
                </div>
              ))}
              {videos.map((v) => (
                <div
                  key={`v-${v.id}`}
                  className="flex justify-between items-center bg-[#182235] rounded px-3 py-2"
                >
                  <span>
                    Video #{v.id} ({v.duration_s ?? "?"}s)
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setClips((prev) => [
                        ...prev,
                        { source_path: v.output_path || "", start_s: 0, duration_s: v.duration_s || 2.5 },
                      ])
                    }
                    className="px-2 py-1 rounded bg-emerald-500/20 text-emerald-300 cursor-pointer"
                  >
                    <Plus className="w-3 h-3 inline" /> Thêm
                  </button>
                </div>
              ))}
            </div>
          </div>

          <form
            onSubmit={renderTimeline}
            className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3"
          >
            <h2 className="text-sm font-semibold text-white">Chuỗi Timeline ({clips.length} clip)</h2>
            <input
              value={projTitle}
              onChange={(e) => setProjTitle(e.target.value)}
              className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            />
            <div className="space-y-1.5">
              {clips.map((c, idx) => (
                <div key={idx} className="flex justify-between items-center bg-[#182235] rounded px-3 py-1.5">
                  <span className="truncate">{c.source_path} ({c.duration_s}s)</span>
                  <button
                    type="button"
                    onClick={() => setClips((prev) => prev.filter((_, i) => i !== idx))}
                    className="text-slate-400 hover:text-rose-400 cursor-pointer"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>
            <input
              value={subText}
              onChange={(e) => setSubText(e.target.value)}
              placeholder="Chữ phụ đề chạy xuyên suốt..."
              className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            />
            <button
              type="submit"
              disabled={clips.length === 0 || jobRunning}
              className="px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold cursor-pointer disabled:opacity-40"
            >
              <Play className="w-3.5 h-3.5 inline mr-1" />{" "}
              {jobRunning ? "Đang xuất..." : "Xuất Video Đa Track"}
            </button>
            {projects.slice(0, 3).map((p) => (
              <div key={p.id} className="text-[11px] text-slate-400 flex justify-between pt-1">
                <span>#{p.id} {p.title} ({p.status})</span>
                {p.output_video_id && (
                  <Link href={`/videos/${p.output_video_id}`} className="text-sky-400 hover:underline">
                    Video #{p.output_video_id}
                  </Link>
                )}
              </div>
            ))}
          </form>
        </div>
      )}
    </div>
  );
}
