"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCheck,
  CheckCircle2,
  Download,
  Eye,
  EyeOff,
  Plus,
  RefreshCw,
  Share2,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { PageHeader } from "@/components/vc/PageHeader";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextInput } from "@/components/ui/form-controls";
import { ModalDialog } from "@/components/ui/overlays";

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

  const [plat, setPlat] = useState<
    "facebook" | "instagram" | "threads" | "tiktok" | "youtube"
  >("youtube");
  const [extId, setExtId] = useState("");
  const [accName, setAccName] = useState("");
  const [accToken, setAccToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [accMode, setAccMode] = useState("inherit");
  const [deleteTarget, setDeleteTarget] = useState<ChannelAccount | null>(null);

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
        apiFetch<{ posts: PostItem[] }>(
          `/api/v1/posts?workspace_id=${activeWorkspaceId}`
        ),
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
      setErr(
        e instanceof Error ? e.message : "Lỗi tải dữ liệu duyệt & lịch đăng"
      );
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
      toast.success("Đã lưu kết nối kênh.");
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
      setErr(
        e2 instanceof Error
          ? e2.message
          : "Chưa cấu hình khóa OAuth trong trang Cài đặt"
      );
    }
  };

  const confirmDeleteAccount = async () => {
    if (!deleteTarget) return;
    await apiFetch(`/api/v1/accounts/${deleteTarget.id}`, { method: "DELETE" });
    toast.success(`Đã gỡ kênh "${deleteTarget.name}".`);
    setDeleteTarget(null);
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

      {/* Pending Approval Queue */}
      <Card tinted className="space-y-4">
        <CardTitleRow>
          <SectionHeading className="tabular-nums">
            Video Chờ Duyệt ({pending.length})
          </SectionHeading>
          {pending.length > 0 && (
            <button
              type="button"
              onClick={() =>
                setSelectedIds(
                  selectedIds.length === pending.length
                    ? []
                    : pending.map((v) => v.id)
                )
              }
              className="text-[12.5px] font-semibold text-[var(--c-tx)] hover:underline cursor-pointer"
            >
              {selectedIds.length === pending.length
                ? "Bỏ chọn tất cả"
                : "Chọn tất cả"}
            </button>
          )}
        </CardTitleRow>

        {pending.length === 0 ? (
          <EmptyState
            icon={<CheckCircle2 className="w-5 h-5" />}
            title="Không có video chờ duyệt"
            description="Tất cả video hoàn tất trong Workspace này đã được kiểm duyệt."
          />
        ) : (
          <div className="grid md:grid-cols-2 gap-4">
            {pending.map((v) => (
              <article
                key={v.id}
                className="rounded-[12px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-4 space-y-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <label className="flex items-center gap-2.5 font-semibold text-[14px] text-[var(--text-primary)] cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(v.id)}
                      onChange={() => toggleSelect(v.id)}
                      className="h-4 w-4 accent-[var(--c-solid)]"
                    />
                    <span>
                      #{v.id} — {v.plan?.title || "Chưa đặt tiêu đề"}
                    </span>
                  </label>
                  <Badge tone="neutral">
                    {v.aspect_ratio} • {v.style_preset}
                  </Badge>
                </div>

                {v.output_url && (
                  <div className="aspect-video w-full overflow-hidden rounded-[9px] bg-black border border-[var(--border-subtle)]">
                    <video
                      controls
                      src={v.output_url}
                      className="h-full w-full object-contain"
                    />
                  </div>
                )}

                {v.unsupported_claims?.length > 0 && (
                  <div className="flex items-start gap-2 rounded-[9px] border border-[var(--st-amber-bd)] bg-[var(--st-amber-bg)] px-3 py-2 text-[12.5px] text-[var(--st-amber-tx)]">
                    <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                    <span>
                      Cảnh báo tuyên bố chưa đối chiếu dữ kiện:{" "}
                      {v.unsupported_claims.join(", ")}
                    </span>
                  </div>
                )}

                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => void singleApprove(v.id)}
                  >
                    <Check className="w-3.5 h-3.5" /> Duyệt đăng
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="danger"
                    onClick={() => void singleReject(v.id)}
                  >
                    <X className="w-3.5 h-3.5" /> Từ chối
                  </Button>
                  {v.output_url && (
                    <Button asChild size="sm" variant="secondary">
                      <a href={`/api/v1/videos/${v.id}/publish-pack`}>
                        <Download className="w-3.5 h-3.5" /> Gói 5 MXH (.zip)
                      </a>
                    </Button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </Card>

      {/* Channels & OAuth */}
      <div className="grid lg:grid-cols-2 gap-4">
        <Card>
          <form onSubmit={addAccount} className="space-y-3.5">
            <CardTitleRow>
              <SectionHeading>
                <Plus className="w-4 h-4 text-[var(--c-icon)]" /> Kết nối Kênh MXH
              </SectionHeading>
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="danger"
                  onClick={() => void startOAuth("youtube")}
                >
                  Đăng nhập YouTube
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => void startOAuth("tiktok")}
                >
                  Đăng nhập TikTok
                </Button>
              </div>
            </CardTitleRow>

            <div className="grid sm:grid-cols-2 gap-3">
              <div>
                <FieldLabel htmlFor="ch-platform">Nền tảng</FieldLabel>
                <SelectBox
                  id="ch-platform"
                  value={plat}
                  onChange={(e) => setPlat(e.target.value as typeof plat)}
                >
                  <option value="youtube">YouTube (Shorts / Video)</option>
                  <option value="tiktok">TikTok</option>
                  <option value="facebook">Facebook Page</option>
                  <option value="instagram">Instagram Reels</option>
                  <option value="threads">Threads</option>
                </SelectBox>
              </div>
              <div>
                <FieldLabel htmlFor="ch-mode">Chế độ duyệt kênh</FieldLabel>
                <SelectBox
                  id="ch-mode"
                  value={accMode}
                  onChange={(e) => setAccMode(e.target.value)}
                >
                  <option value="inherit">Theo cài đặt Workspace</option>
                  <option value="single">Luôn hỏi duyệt từng bài</option>
                  <option value="bulk">Duyệt theo lô</option>
                  <option value="autopilot">Tự đăng khi đạt kiểm định QC</option>
                </SelectBox>
              </div>
            </div>

            <div className="grid sm:grid-cols-2 gap-3">
              <div>
                <FieldLabel htmlFor="ch-ext-id">Mã định danh kênh (ID) *</FieldLabel>
                <TextInput
                  id="ch-ext-id"
                  required
                  value={extId}
                  onChange={(e) => setExtId(e.target.value)}
                  placeholder="VD: UC_x925..."
                />
              </div>
              <div>
                <FieldLabel htmlFor="ch-name">Tên kênh hiển thị *</FieldLabel>
                <TextInput
                  id="ch-name"
                  required
                  value={accName}
                  onChange={(e) => setAccName(e.target.value)}
                  placeholder="VD: Trang Sức Bạc Official"
                />
              </div>
            </div>

            <div>
              <FieldLabel htmlFor="ch-token">
                Mã truy cập (Access Token — mã hóa cục bộ)
              </FieldLabel>
              <div className="relative">
                <TextInput
                  id="ch-token"
                  type={showToken ? "text" : "password"}
                  value={accToken}
                  onChange={(e) => setAccToken(e.target.value)}
                  placeholder="Dán mã truy cập nếu cấu hình thủ công..."
                  className="pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowToken((v) => !v)}
                  aria-label={showToken ? "Ẩn mã truy cập" : "Hiện mã truy cập"}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
                >
                  {showToken ? (
                    <EyeOff className="w-4 h-4" />
                  ) : (
                    <Eye className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>

            <Button type="submit">Thêm Kênh vào Workspace</Button>
          </form>
        </Card>

        <Card className="space-y-3">
          <SectionHeading className="tabular-nums">
            Kênh đang gắn Workspace ({accounts.length})
          </SectionHeading>
          {accounts.length === 0 ? (
            <EmptyState
              title="Chưa kết nối kênh mạng xã hội nào"
              description="Thêm kênh ở khung bên trái hoặc đăng nhập OAuth để lên lịch đăng tự động."
            />
          ) : (
            <div className="space-y-2 max-h-72 overflow-y-auto">
              {accounts.map((a) => (
                <div
                  key={a.id}
                  className="flex items-center justify-between gap-2 rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3.5 py-2.5"
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <Badge tone="sky" className="uppercase text-[11px] px-2 py-0">
                        {a.platform}
                      </Badge>
                      <strong className="text-[13.5px] text-[var(--text-primary)]">
                        {a.name}
                      </strong>
                    </div>
                    <div className="mt-0.5 text-[12px] text-[var(--text-muted)]">
                      Chế độ: {a.approval_mode} • Khóa truy cập:{" "}
                      {a.has_token ? "Đã mã hóa" : "Chưa đặt"}
                    </div>
                  </div>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label={`Xóa kênh ${a.name}`}
                    onClick={() => setDeleteTarget(a)}
                  >
                    <Trash2 className="w-4 h-4 text-rose-400" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Posts Schedule & Performance */}
      <div className="grid lg:grid-cols-2 gap-4">
        <Card className="space-y-3">
          <SectionHeading className="tabular-nums">
            Lịch đăng ({posts.length})
          </SectionHeading>
          {posts.length === 0 ? (
            <EmptyState title="Chưa có bài đăng nào trong lịch" />
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {posts.map((p) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between gap-2 rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3.5 py-2.5"
                >
                  <div>
                    <div className="text-[13.5px] font-semibold text-[var(--text-primary)]">
                      Video #{p.video_id} → {p.platform} ({p.account_name})
                    </div>
                    <div className="text-[12px] text-[var(--text-muted)] tabular-nums">
                      {p.status} • {p.scheduled_at}
                    </div>
                  </div>
                  {["failed", "missed"].includes(p.status) && (
                    <Button
                      type="button"
                      size="sm"
                      variant="amber"
                      onClick={() => void retryPost(p.id)}
                    >
                      <RefreshCw className="w-3.5 h-3.5" /> Thử lại
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card className="space-y-3">
          <SectionHeading className="tabular-nums">
            Hiệu quả sau 24 giờ / 72 giờ / 7 ngày ({perf.length})
          </SectionHeading>
          {perf.length === 0 ? (
            <EmptyState title="Chưa có số liệu hiệu quả bài đăng" />
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {perf.map((item) => (
                <div
                  key={item.post_id}
                  className="rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3.5 py-2.5 space-y-1"
                >
                  <div className="text-[13.5px] font-semibold text-[var(--text-primary)]">
                    {item.title} ({item.platform})
                  </div>
                  <div className="text-[12px] text-[var(--text-muted)] tabular-nums">
                    24h: {item.checkpoints?.["24h"]?.views ?? "—"} lượt xem • 72h:{" "}
                    {item.checkpoints?.["72h"]?.views ?? "—"} lượt xem • 7d:{" "}
                    {item.checkpoints?.["7d"]?.views ?? "—"} lượt xem
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <ModalDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(o) => {
          if (!o) setDeleteTarget(null);
        }}
        title="Xác nhận gỡ kết nối kênh"
        description={
          deleteTarget
            ? `Bạn có chắc muốn gỡ kênh "${deleteTarget.name}" (${deleteTarget.platform}) khỏi Workspace hiện tại không?`
            : ""
        }
      >
        <div className="flex justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="secondary"
            onClick={() => setDeleteTarget(null)}
          >
            Hủy
          </Button>
          <Button
            type="button"
            variant="danger"
            onClick={() => void confirmDeleteAccount()}
          >
            Gỡ kênh
          </Button>
        </div>
      </ModalDialog>
    </div>
  );
}
