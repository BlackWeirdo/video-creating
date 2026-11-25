"use client";

import React, { useState } from "react";
import { Eye, EyeOff, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import type { ChannelAccount, SocialPlatform } from "@/app/approval/types";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextInput } from "@/components/ui/form-controls";
import { ModalDialog } from "@/components/ui/overlays";

export function ChannelsAndOAuthPanel({
  workspaceId,
  accounts,
  onReload,
  onMessage,
  onError,
}: {
  workspaceId: number;
  accounts: ChannelAccount[];
  onReload: () => Promise<void>;
  onMessage: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [plat, setPlat] = useState<SocialPlatform>("youtube");
  const [extId, setExtId] = useState("");
  const [accName, setAccName] = useState("");
  const [accToken, setAccToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [accMode, setAccMode] = useState("inherit");
  const [deleteTarget, setDeleteTarget] = useState<ChannelAccount | null>(null);

  const addAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    onError("");
    try {
      await apiFetch("/api/v1/accounts", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId,
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
      onMessage("Đã lưu kết nối kênh.");
      toast.success("Đã lưu kết nối kênh.");
      await onReload();
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Lỗi thêm kênh");
    }
  };

  const startOAuth = async (oauthPlat: "threads" | "tiktok" | "youtube") => {
    onError("");
    try {
      const res = await apiFetch<{ authorize_url: string }>(
        `/api/v1/oauth/${oauthPlat}/authorize`,
        {
          method: "POST",
          body: JSON.stringify({ workspace_id: workspaceId }),
        }
      );
      window.open(res.authorize_url, "_blank");
    } catch (e2) {
      onError(
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
    await onReload();
  };

  return (
    <>
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
                  onChange={(e) => setPlat(e.target.value as SocialPlatform)}
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
    </>
  );
}
