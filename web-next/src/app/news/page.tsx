"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Download, Newspaper, Play, Sparkles } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";

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
}

export default function NewsPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [projects, setProjects] = useState<NewsProject[]>([]);
  const [sourceKind, setSourceKind] = useState<"url" | "rss" | "raw_text">("raw_text");
  const [title, setTitle] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [rawText, setRawText] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await apiFetch<{ projects: NewsProject[] }>(
        `/api/v1/news/projects?workspace_id=${activeWorkspaceId}`
      );
      setProjects(res.projects || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Studio Tin tức");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const createNews = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const res = await apiFetch<{ project: NewsProject }>("/api/v1/news/projects", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          title,
          source_kind: sourceKind,
          source_url: sourceUrl,
          raw_text: rawText,
        }),
      });
      setTitle("");
      setSourceUrl("");
      setRawText("");
      setMsg(`Đã tạo dự án Tin tức #${res.project.id}.`);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không tạo được dự án");
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Newspaper className="w-6 h-6 text-amber-400" /> Studio Tin tức / Bài viết → Video
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Đọc bài báo URL / RSS / văn bản, giữ nguyên số liệu thực tế &amp; xuất MP4 kèm gói đăng bài `.zip`.
        </p>
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

      <form
        onSubmit={createNews}
        className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs"
      >
        <div className="grid md:grid-cols-3 gap-3">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Tiêu đề bản tin"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <select
            value={sourceKind}
            onChange={(e) => setSourceKind(e.target.value as "url" | "rss" | "raw_text")}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="raw_text">Dán nội dung bài viết</option>
            <option value="url">Đọc từ URL bài báo</option>
            <option value="rss">Đọc từ RSS Feed</option>
          </select>
          {sourceKind !== "raw_text" && (
            <input
              required
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              placeholder="https://... hoặc rss URL"
              className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            />
          )}
        </div>
        {sourceKind === "raw_text" && (
          <textarea
            required
            rows={4}
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            placeholder="Dán nội dung tin tức, giữ nguyên con số quan trọng..."
            className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
        )}
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-slate-950 font-semibold cursor-pointer"
        >
          Tạo Bản Tin
        </button>
      </form>

      <div className="space-y-3 text-xs">
        {projects.map((p) => (
          <div
            key={p.id}
            className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-2.5"
          >
            <div className="flex items-center justify-between">
              <div className="font-semibold text-white">
                {p.title}{" "}
                <span className="text-[11px] text-sky-300 font-normal">
                  ({p.source_kind} • {p.status})
                </span>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={async () => {
                    await apiFetch(`/api/v1/news/projects/${p.id}/summarize`, { method: "POST" });
                    setMsg(`Đã trích số liệu & tóm tắt kịch bản cho Bản tin #${p.id}.`);
                    await load();
                  }}
                  className="px-2.5 py-1 rounded bg-slate-800 text-amber-300 cursor-pointer"
                >
                  <Sparkles className="w-3 h-3 inline mr-1" /> Tóm tắt &amp; Giữ số liệu
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    const res = await apiFetch<{ job_id: number }>(
                      `/api/v1/news/projects/${p.id}/render`,
                      { method: "POST", body: JSON.stringify({ sync: false, build_pack: true }) }
                    );
                    setMsg(`Đã xếp hàng render Bản tin #${p.id} (Job #${res.job_id}).`);
                  }}
                  className="px-2.5 py-1 rounded bg-emerald-500/20 text-emerald-300 cursor-pointer"
                >
                  <Play className="w-3 h-3 inline mr-1" /> Render + Gói .zip
                </button>
              </div>
            </div>
            {p.facts?.preserved_tokens && p.facts.preserved_tokens.length > 0 && (
              <div className="text-[11px] text-amber-300">
                Số liệu bảo toàn: {p.facts.preserved_tokens.join(" • ")}
              </div>
            )}
            {p.script && p.script.length > 0 && (
              <div className="grid md:grid-cols-3 gap-2">
                {p.script.map((s, idx) => (
                  <div key={idx} className="bg-[#182235] rounded p-2 text-[11px] text-slate-300">
                    <div className="text-slate-500 uppercase text-[10px]">{s.role}</div>
                    <div>{s.text}</div>
                  </div>
                ))}
              </div>
            )}
            <div className="flex gap-3">
              {p.output_video_id && (
                <Link href={`/videos/${p.output_video_id}`} className="text-sky-400 hover:underline">
                  Xem Video #{p.output_video_id}
                </Link>
              )}
              {p.publish_pack_path && (
                <a
                  href={`/files/${p.publish_pack_path}`}
                  className="inline-flex items-center gap-1 text-emerald-300 hover:underline"
                >
                  <Download className="w-3 h-3" /> Tải Gói Đăng Bài (.zip)
                </a>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
