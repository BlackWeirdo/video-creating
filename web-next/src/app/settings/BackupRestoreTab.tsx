"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Archive, Download, Rocket, Upload } from "lucide-react";
import { toast } from "sonner";
import { apiFetch, apiFetchBlob } from "@/lib/api";
import { BackupSummary } from "@/app/settings/types";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, TextInput } from "@/components/ui/form-controls";
import { ModalDialog } from "@/components/ui/overlays";

export function BackupRestoreTab({
  backupSummary,
  onReload,
  onMessage,
  onError,
}: {
  backupSummary: BackupSummary | null;
  onReload: () => Promise<void>;
  onMessage: (m: string) => void;
  onError: (m: string) => void;
}) {
  const [backupPassword, setBackupPassword] = useState("");
  const [restorePassword, setRestorePassword] = useState("");
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [restoring, setRestoring] = useState(false);

  const handleExport = async () => {
    onError("");
    onMessage("");
    try {
      const blob = await apiFetchBlob("/api/v1/backup/export", {
        method: "POST",
        body: JSON.stringify({ password: backupPassword, save_copy: true }),
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "videocreator-v2-backup.vcx";
      a.click();
      URL.revokeObjectURL(url);
      setBackupPassword("");
      const m = "Đã xuất gói sao lưu .vcx mã hóa và lưu bản cục bộ.";
      onMessage(m);
      toast.success(m);
      await onReload();
    } catch (err) {
      onError(
        err instanceof Error
          ? err.message
          : "Xuất sao lưu thất bại (kiểm tra mật khẩu từ 4 ký tự trở lên)."
      );
    }
  };

  const executeRestore = async () => {
    if (!restoreFile) return;
    onError("");
    onMessage("");
    setRestoring(true);
    try {
      const fd = new FormData();
      fd.append("file", restoreFile);
      fd.append("password", restorePassword);
      fd.append("as_server", "true");
      const res = await apiFetch<{ pre_restore_backup?: string }>(
        "/api/v1/backup/restore",
        { method: "POST", body: fd }
      );
      setRestorePassword("");
      setRestoreFile(null);
      setConfirmOpen(false);
      const bkNote = res.pre_restore_backup
        ? ` (đã tự lưu bản cũ: ${res.pre_restore_backup})`
        : "";
      const m = `Đã khôi phục toàn bộ Workspaces, CSDL và Khóa API từ gói .vcx${bkNote}!`;
      onMessage(m);
      toast.success(m);
      await onReload();
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Khôi phục gói .vcx thất bại");
      setConfirmOpen(false);
    } finally {
      setRestoring(false);
    }
  };

  return (
    <Card tinted className="space-y-4">
      <CardTitleRow>
        <SectionHeading>
          <Archive className="w-4 h-4 text-[var(--c-icon)]" /> Sao lưu &amp; Khôi phục Cấu hình Mã hóa (.vcx)
        </SectionHeading>
        <Button asChild size="sm" variant="secondary">
          <Link href="/welcome">
            <Rocket className="w-3.5 h-3.5 text-[var(--c-icon)]" /> Mở Hướng dẫn thiết lập
          </Link>
        </Button>
      </CardTitleRow>

      {backupSummary && (
        <div className="flex flex-wrap gap-2">
          <Badge tone="neutral" className="tabular-nums">
            CSDL: {(backupSummary.db_size_bytes / 1024).toFixed(1)} KB
          </Badge>
          <Badge tone="cluster" className="tabular-nums">
            {backupSummary.workspaces} Workspaces
          </Badge>
          <Badge tone="sky" className="tabular-nums">
            {backupSummary.products} sản phẩm • {backupSummary.workflows} quy trình
          </Badge>
          <Badge tone="emerald" className="tabular-nums">
            {backupSummary.secrets_count} khóa bảo mật
          </Badge>
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        <div className="rounded-[12px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-4 space-y-3">
          <div className="text-[14px] font-bold text-[var(--text-primary)]">
            Xuất gói Sao lưu Mã hóa (.vcx)
          </div>
          <div>
            <FieldLabel htmlFor="bk-export-pw">
              Mật khẩu mã hóa (tối thiểu 4 ký tự)
            </FieldLabel>
            <TextInput
              id="bk-export-pw"
              type="password"
              value={backupPassword}
              onChange={(e) => setBackupPassword(e.target.value)}
              placeholder="Nhập mật khẩu bảo vệ tệp .vcx..."
            />
          </div>
          <Button type="button" onClick={() => void handleExport()}>
            <Download className="w-4 h-4" /> Tải tệp sao lưu .vcx
          </Button>
        </div>

        <div className="rounded-[12px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-4 space-y-3">
          <div className="text-[14px] font-bold text-[var(--text-primary)]">
            Khôi phục từ tệp .vcx
          </div>
          <div>
            <FieldLabel htmlFor="bk-restore-file">Chọn tệp sao lưu (.vcx)</FieldLabel>
            <input
              id="bk-restore-file"
              type="file"
              accept=".vcx"
              onChange={(e) => setRestoreFile(e.target.files?.[0] || null)}
              className="block w-full text-[12.5px] text-[var(--text-secondary)] file:mr-3 file:rounded-md file:border file:border-[var(--border-strong)] file:bg-[var(--bg-card)] file:px-3 file:py-1 file:text-[12px] file:font-semibold file:text-[var(--text-primary)] file:cursor-pointer"
            />
          </div>
          <div>
            <FieldLabel htmlFor="bk-restore-pw">Mật khẩu giải mã tệp .vcx</FieldLabel>
            <TextInput
              id="bk-restore-pw"
              type="password"
              value={restorePassword}
              onChange={(e) => setRestorePassword(e.target.value)}
              placeholder="Nhập mật khẩu giải mã..."
            />
          </div>
          <Button
            type="button"
            variant="emerald"
            disabled={!restoreFile}
            onClick={() => setConfirmOpen(true)}
          >
            <Upload className="w-4 h-4" /> Khôi phục gói .vcx
          </Button>
        </div>
      </div>

      <ModalDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Xác nhận khôi phục gói cấu hình .vcx"
        description="Thao tác này sẽ ghi đè cấu hình, cơ sở dữ liệu và khóa API hiện tại. Hệ thống luôn tự động tạo một bản sao lưu dự phòng (pre-restore-*.vcx) trước khi ghi đè."
      >
        <div className="flex justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="secondary"
            onClick={() => setConfirmOpen(false)}
          >
            Hủy
          </Button>
          <Button
            type="button"
            variant="emerald"
            disabled={restoring}
            onClick={() => void executeRestore()}
          >
            {restoring ? "Đang khôi phục..." : "Đồng ý khôi phục"}
          </Button>
        </div>
      </ModalDialog>
    </Card>
  );
}
