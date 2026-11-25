"use client";

import React, { useState } from "react";
import { ChevronsUpDown, Plus } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace, Workspace } from "@/lib/api";
import { PolicyBadge } from "@/components/vc/PolicyBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextInput } from "@/components/ui/form-controls";
import {
  DropdownItem,
  DropdownPanel,
  DropdownRoot,
  DropdownSeparator,
  DropdownTrigger,
  HintTooltip,
  ModalDialog,
} from "@/components/ui/overlays";
import { cn } from "@/lib/utils";

const APPROVAL_LABEL: Record<Workspace["approval_mode"], string> = {
  single: "Duyệt từng bài",
  bulk: "Duyệt hàng loạt",
  autopilot: "Tự động đăng",
};

export function WorkspaceSwitcher({
  collapsed,
  onOpenCreate,
}: {
  collapsed: boolean;
  onOpenCreate: () => void;
}) {
  const { workspaces, activeWorkspaceId, activeWorkspace, activateWorkspace } =
    useWorkspace();

  const triggerBtn = (
    <DropdownTrigger asChild>
      <button
        type="button"
        aria-label="Chuyển đổi Workspace thương hiệu"
        className={cn(
          "w-full rounded-[10px] border border-[var(--border-strong)] bg-[var(--bg-elevated)] text-left transition-all duration-150 hover:border-[var(--c-bd)] cursor-pointer",
          collapsed ? "flex items-center justify-center p-2" : "px-3 py-2 space-y-1.5"
        )}
      >
        <div className="flex items-center justify-between gap-1.5">
          {!collapsed && (
            <span className="truncate text-[13px] font-semibold text-[var(--text-primary)]">
              {activeWorkspace?.name || "Workspace Mặc định"}
            </span>
          )}
          <ChevronsUpDown className="w-4 h-4 shrink-0 text-[var(--text-muted)]" />
        </div>
        {!collapsed && activeWorkspace && (
          <div className="flex flex-wrap items-center gap-1.5">
            <PolicyBadge policy={activeWorkspace.content_policy} />
            <Badge tone="neutral" className="text-[11px] px-2 py-0">
              {APPROVAL_LABEL[activeWorkspace.approval_mode] || activeWorkspace.approval_mode}
            </Badge>
          </div>
        )}
      </button>
    </DropdownTrigger>
  );

  return (
    <DropdownRoot>
      <HintTooltip
        enabled={collapsed}
        label={`Workspace: ${activeWorkspace?.name || "Mặc định"}`}
      >
        {triggerBtn}
      </HintTooltip>

      <DropdownPanel className="w-[264px]">
        <div className="px-2 py-1 text-[11.5px] font-semibold text-[var(--text-muted)]">
          Chọn thương hiệu / Workspace
        </div>
        <div className="max-h-60 overflow-y-auto space-y-0.5">
          {workspaces.map((ws) => {
            const isCurrent = ws.id === activeWorkspaceId;
            return (
              <DropdownItem
                key={ws.id}
                onSelect={() => void activateWorkspace(ws.id)}
                className={cn(
                  "flex flex-col gap-1 rounded-[8px] px-2.5 py-2 outline-none cursor-pointer transition-colors",
                  isCurrent
                    ? "bg-[var(--c-soft)] border border-[var(--c-bd)]"
                    : "border border-transparent hover:bg-[var(--bg-elevated)]"
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[13px] font-semibold text-[var(--text-primary)]">
                    {ws.name}
                  </span>
                  <span className="text-[11px] text-[var(--text-muted)]">{ws.niche}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <PolicyBadge policy={ws.content_policy} />
                </div>
              </DropdownItem>
            );
          })}
        </div>
        <DropdownSeparator className="my-1.5 h-px bg-[var(--border-subtle)]" />
        <DropdownItem
          onSelect={onOpenCreate}
          className="flex items-center gap-2 rounded-[8px] px-2.5 py-2 text-[13px] font-semibold text-[var(--c-tx)] hover:bg-[var(--c-soft)] outline-none cursor-pointer"
        >
          <Plus className="w-4 h-4" /> Tạo Workspace mới...
        </DropdownItem>
      </DropdownPanel>
    </DropdownRoot>
  );
}

export function CreateWorkspaceDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { activateWorkspace } = useWorkspace();
  const [wsName, setWsName] = useState("");
  const [wsNiche, setWsNiche] = useState("general");
  const [wsPolicy, setWsPolicy] =
    useState<Workspace["content_policy"]>("strict_footage");
  const [wsApproval, setWsApproval] =
    useState<Workspace["approval_mode"]>("single");
  const [wsRatio, setWsRatio] =
    useState<Workspace["default_aspect_ratio"]>("9:16");
  const [wsErr, setWsErr] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setWsErr("");
    setSubmitting(true);
    try {
      const res = await apiFetch<{ workspace: Workspace }>("/api/v1/workspaces", {
        method: "POST",
        body: JSON.stringify({
          name: wsName,
          niche: wsNiche,
          content_policy: wsPolicy,
          approval_mode: wsApproval,
          default_aspect_ratio: wsRatio,
        }),
      });
      await activateWorkspace(res.workspace.id);
      toast.success(`Đã tạo và chuyển sang Workspace "${res.workspace.name}"`);
      setWsName("");
      onOpenChange(false);
    } catch (err) {
      setWsErr(err instanceof Error ? err.message : "Không thể tạo Workspace");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Tạo Workspace Thương Hiệu Mới"
      description="Mỗi Workspace tách biệt sản phẩm, kho cảnh quay, chính sách nội dung và kênh đăng."
    >
      <form onSubmit={handleSubmit} className="space-y-3.5">
        {wsErr && (
          <div
            role="alert"
            className="rounded-[9px] border border-[var(--st-rose-bd)] bg-[var(--st-rose-bg)] px-3 py-2 text-[12.5px] text-[var(--st-rose-tx)]"
          >
            {wsErr}
          </div>
        )}
        <div>
          <FieldLabel htmlFor="ws-create-name">Tên thương hiệu / Dự án *</FieldLabel>
          <TextInput
            id="ws-create-name"
            required
            value={wsName}
            onChange={(e) => setWsName(e.target.value)}
            placeholder="VD: Trang Sức Bạc S925"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <FieldLabel htmlFor="ws-create-niche">Ngành hàng</FieldLabel>
            <TextInput
              id="ws-create-niche"
              value={wsNiche}
              onChange={(e) => setWsNiche(e.target.value)}
            />
          </div>
          <div>
            <FieldLabel htmlFor="ws-create-ratio">Khung hình ưu tiên</FieldLabel>
            <SelectBox
              id="ws-create-ratio"
              value={wsRatio}
              onChange={(e) =>
                setWsRatio(e.target.value as Workspace["default_aspect_ratio"])
              }
            >
              <option value="9:16">9:16 (Dọc Shorts/Reels)</option>
              <option value="16:9">16:9 (Ngang YouTube)</option>
              <option value="1:1">1:1 (Vuông)</option>
            </SelectBox>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <FieldLabel htmlFor="ws-create-policy">Chính sách nội dung</FieldLabel>
            <SelectBox
              id="ws-create-policy"
              value={wsPolicy}
              onChange={(e) =>
                setWsPolicy(e.target.value as Workspace["content_policy"])
              }
            >
              <option value="strict_footage">Strict Footage (Chuẩn hãng)</option>
              <option value="hybrid_remix">Hybrid Remix (Kết hợp Shot thật)</option>
              <option value="full_ai">Full AI (Kênh vệ tinh / Reup)</option>
            </SelectBox>
          </div>
          <div>
            <FieldLabel htmlFor="ws-create-approval">Chế độ duyệt</FieldLabel>
            <SelectBox
              id="ws-create-approval"
              value={wsApproval}
              onChange={(e) =>
                setWsApproval(e.target.value as Workspace["approval_mode"])
              }
            >
              <option value="single">Duyệt từng bài</option>
              <option value="bulk">Duyệt hàng loạt</option>
              <option value="autopilot">Tự động đăng (Autopilot)</option>
            </SelectBox>
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="secondary"
            onClick={() => onOpenChange(false)}
          >
            Hủy
          </Button>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Đang tạo..." : "Tạo & Chuyển ngay"}
          </Button>
        </div>
      </form>
    </ModalDialog>
  );
}
