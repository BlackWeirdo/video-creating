"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Check, CheckCheck, Download, Plus, RefreshCw, Share2, Trash2, X } from "lucide-react";
import { apiFetch, useWorkspace } from "@/lib/api";

interface ApprovalVideo {
  id: number;
  status: string;
  aspect_ratio: string;
  style_preset: string;
  duration_s: number | null;
  output_url: string | null;
  quality_score: number | null;
  unsupported_claims: string[];
  plan: { title?: string };
  qc: { passed?: boolean; issues?: string[] };
}

interface ChannelAccount {
  id: number;
  platform: string;
  external_id: string;
  name: string;
  lang: string;
  approval_mode: string;
  autopilot_min_score: number;
  slots: string[];
  enabled: boolean;
  has_token: boolean;
}

interface PostItem {
  id: number;
  video_id: number;
  platform: string;
  account_name: string;
  status: string;
  scheduled_at: string;
  permalink: string | null;
  error: string | null;
}

interface PerfItem {
  post_id: number;
  video_id: number;
  title: string;
  platform: string;
  account_name: string;
  checkpoints: Record<
    string,
    { views?: number | null; likes?: number | null; comments?: number | null } | null
  >;
}

export default function ApprovalAndPublishingPage() {
  const { activeWorkspaceId } = useWorkspace();
  const [pending, setPending] = useState<ApprovalVideo[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [accounts, setAccounts] = useState<ChannelAccount[]>([]);
  const [posts, setPosts] = useState<PostItem[]>([]);
  const [perf, setPerf] = useState<PerfItem[]>([]);

  const [plat, setPlat] = useState<"facebook" | "instagram" | "threads" | "tiktok" | "youtube">("youtube");
  const [extId, setExtId] = useState("");
  const [accName, setAccName] = useState("");
  const [accToken, setAccToken] = useState("");
  const [accMode, setAccMode] = useState("inherit");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [aRes, cRes, pRes, mRes] = await Promise.all([
        apiFetch<{ pending: ApprovalVideo[] }>(
          `/api/v1/approvals?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ accounts: ChannelAccount[] }>(
          `/api/v1/accounts?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ posts: PostItem[] }>(`/api/v1/posts?workspace_id=${activeWorkspaceId}`),
        apiFetch<{ items: PerfItem[] }>(
          `/api/v1/performance?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      setPending(aRes.pending || []);
      setAccounts(cRes.accounts || []);
      setPosts(pRes.posts || []);
      setPerf(mRes.items || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải dữ liệu duyệt & lịch đăng");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

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
      setMsg(`Đã duyệt Video #${id}.`);
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
    setMsg(`Đã từ chối Video #${id}.`);
    await load();
  };

  const handleBulkApprove = async () => {
    if (selectedIds.length === 0) return;
    setErr("");
    const res = await apiFetch<{ approved_ids: number[]; errors: Record<string, string> }>(
      "/api/v1/approvals/bulk-approve",
      {
        method: "POST",
        body: JSON.stringify({ video_ids: selectedIds, enforce_policy: true }),
      }
    );
    setSelectedIds([]);
    const errCount = Object.keys(res.errors || {}).length;
    setMsg(
      `Duyệt hàng loạt: ${res.approved_ids.length} thành công` +
        (errCount > 0 ? `, ${errCount} bị chặn bởi chính sách strict_footage.` : ".")
    );
    await load();
  };

  const addAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    try {
      await apiFetch("/api/v1/accounts", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          platform: plat,
          external_id: extId,
          name: accName,
          access_token: accToken,
          approval_mode: accMode,
        }),
      });
      setExtId("");
      setAccName("");
      setAccToken("");
      setMsg("Đã lưu kết nối kênh.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi thêm kênh");
    }
  };

  const startOAuth = async (oauthPlat: "threads" | "tiktok" | "youtube") => {
    setErr("");
    try {
      const res = await apiFetch<{ authorize_url: string }>(
        `/api/v1/oauth/${oauthPlat}/authorize`,
        {
          method: "POST",
          body: JSON.stringify({ workspace_id: activeWorkspaceId }),
        }
      );
      window.open(res.authorize_url, "_blank");
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Chưa cấu hình OAuth App Key trong Settings");
    }
  };

  const deleteAccount = async (id: number) => {
    await apiFetch(`/api/v1/accounts/${id}`, { method: "DELETE" });
    await load();
  };

  const retryPost = async (id: number) => {
    await apiFetch(`/api/v1/posts/${id}/retry`, { method: "POST" });
    setMsg(`Đã xếp lịch chạy lại Post #${id}.`);
    await load();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Share2 className="w-6 h-6 text-emerald-400" /> Duyệt bài, Kênh 5 MXH & Lịch đăng
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Hỗ trợ duyệt từng bài, duyệt hàng loạt, tải Gói `.zip` 5 nền tảng (gồm YouTube Shorts/Video) & Autopilot.
          </p>
        </div>
        {selectedIds.length > 0 && (
          <button
            onClick={() => void handleBulkApprove()}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-xs cursor-pointer"
          >
            <CheckCheck className="w-4 h-4" /> Duyệt Hàng Loạt ({selectedIds.length})
          </button>
        )}
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

      {/* Pending Approval Queue */}
      <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs">
        <h2 className="text-sm font-semibold text-white">
          Video Chờ Duyệt ({pending.length})
        </h2>
        {pending.length === 0 ? (
          <div className="text-slate-500">Không có video chờ duyệt trong Workspace này.</div>
        ) : (
          <div className="grid md:grid-cols-2 gap-4">
            {pending.map((v) => (
              <div
                key={v.id}
                className="bg-[#182235] border border-slate-700/70 rounded-xl p-4 space-y-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <label className="flex items-center gap-2 font-semibold text-white cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(v.id)}
                      onChange={() => toggleSelect(v.id)}
                    />
                    <span>
                      #{v.id} — {v.plan?.title || "Chưa đặt tiêu đề"}
                    </span>
                  </label>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                    {v.aspect_ratio} • {v.style_preset}
                  </span>
                </div>
                {v.output_url && (
                  <video
                    controls
                    src={v.output_url}
                    className="w-full h-44 rounded bg-black object-contain"
                  />
                )}
                {v.unsupported_claims?.length > 0 && (
                  <div className="text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded px-2.5 py-1.5">
                    Cảnh báo tuyên bố chưa kiểm chứng: {v.unsupported_claims.join(", ")}
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => void singleApprove(v.id)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-emerald-500 text-slate-950 font-semibold cursor-pointer"
                  >
                    <Check className="w-3.5 h-3.5" /> Duyệt
                  </button>
                  <button
                    onClick={() => void singleReject(v.id)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30 cursor-pointer"
                  >
                    <X className="w-3.5 h-3.5" /> Từ chối
                  </button>
                  {v.output_url && (
                    <a
                      href={`/api/v1/videos/${v.id}/publish-pack`}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-slate-800 text-sky-300 border border-slate-700"
                    >
                      <Download className="w-3.5 h-3.5" /> Gói .zip
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Channels & OAuth */}
      <div className="grid md:grid-cols-2 gap-4 text-xs">
        <form
          onSubmit={addAccount}
          className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3"
        >
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
              <Plus className="w-4 h-4 text-sky-400" /> Kết nối Kênh MXH (5 nền tảng)
            </h2>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => void startOAuth("youtube")}
                className="text-[11px] text-rose-300 hover:underline cursor-pointer"
              >
                OAuth YouTube
              </button>
              <button
                type="button"
                onClick={() => void startOAuth("tiktok")}
                className="text-[11px] text-sky-300 hover:underline cursor-pointer"
              >
                OAuth TikTok
              </button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2.5">
            <select
              value={plat}
              onChange={(e) => setPlat(e.target.value as typeof plat)}
              className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            >
              <option value="youtube">YouTube (Shorts/Video)</option>
              <option value="tiktok">TikTok</option>
              <option value="facebook">Facebook Page</option>
              <option value="instagram">Instagram Reels</option>
              <option value="threads">Threads</option>
            </select>
            <select
              value={accMode}
              onChange={(e) => setAccMode(e.target.value)}
              className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            >
              <option value="inherit">Duyệt theo Workspace</option>
              <option value="single">Single (Luôn hỏi duyệt)</option>
              <option value="bulk">Bulk (Duyệt lô)</option>
              <option value="autopilot">Autopilot (Tự đăng đạt QC)</option>
            </select>
          </div>
          <div className="grid grid-cols-2 gap-2.5">
            <input
              required
              value={extId}
              onChange={(e) => setExtId(e.target.value)}
              placeholder="Channel ID / External ID *"
              className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            />
            <input
              required
              value={accName}
              onChange={(e) => setAccName(e.target.value)}
              placeholder="Tên kênh hiển thị *"
              className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            />
          </div>
          <input
            type="password"
            value={accToken}
            onChange={(e) => setAccToken(e.target.value)}
            placeholder="Access Token (mã hóa vào secrets_store)"
            className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <button
            type="submit"
            className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
          >
            Thêm Kênh vào Workspace
          </button>
        </form>

        <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-2.5">
          <h2 className="text-sm font-semibold text-white">
            Kênh đang gắn Workspace ({accounts.length})
          </h2>
          <div className="space-y-2 max-h-60 overflow-y-auto">
            {accounts.map((a) => (
              <div
                key={a.id}
                className="flex items-center justify-between bg-[#182235] rounded-lg px-3 py-2"
              >
                <div>
                  <span className="uppercase text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-sky-300 mr-2">
                    {a.platform}
                  </span>
                  <strong className="text-white">{a.name}</strong>
                  <div className="text-[11px] text-slate-400 mt-0.5">
                    Mode: {a.approval_mode} • Token: {a.has_token ? "Đã lưu" : "Chưa có"}
                  </div>
                </div>
                <button
                  onClick={() => void deleteAccount(a.id)}
                  className="text-slate-400 hover:text-rose-400 cursor-pointer"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Posts Schedule & Performance */}
      <div className="grid md:grid-cols-2 gap-4 text-xs">
        <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3">
          <h2 className="text-sm font-semibold text-white">Lịch đăng ({posts.length})</h2>
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {posts.map((p) => (
              <div
                key={p.id}
                className="flex items-center justify-between bg-[#182235] rounded-lg px-3 py-2"
              >
                <div>
                  <div className="text-white font-medium">
                    Video #{p.video_id} → {p.platform} ({p.account_name})
                  </div>
                  <div className="text-[11px] text-slate-400">
                    {p.status} • {p.scheduled_at}
                  </div>
                </div>
                {["failed", "missed"].includes(p.status) && (
                  <button
                    onClick={() => void retryPost(p.id)}
                    className="inline-flex items-center gap-1 text-amber-300 hover:underline cursor-pointer"
                  >
                    <RefreshCw className="w-3 h-3" /> Thử lại
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3">
          <h2 className="text-sm font-semibold text-white">
            Hiệu quả 24h / 72h / 7d ({perf.length})
          </h2>
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {perf.map((item) => (
              <div key={item.post_id} className="bg-[#182235] rounded-lg px-3 py-2 space-y-1">
                <div className="font-medium text-white">
                  {item.title} ({item.platform})
                </div>
                <div className="text-[11px] text-slate-400">
                  24h: {item.checkpoints?.["24h"]?.views ?? "—"} views • 72h:{" "}
                  {item.checkpoints?.["72h"]?.views ?? "—"} views • 7d:{" "}
                  {item.checkpoints?.["7d"]?.views ?? "—"} views
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
