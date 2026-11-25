"use client";

import React, { useState } from "react";
import { ExternalLink, Plus, RefreshCw, Trash2, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import type { MuseCombo, MusePoolAccount } from "@/app/muse/types";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextInput } from "@/components/ui/form-controls";

export function AccountsAndPoolSection({
  accounts,
  poolStrategy,
  combos,
  onReload,
  onMessage,
  onError,
}: {
  accounts: MusePoolAccount[];
  poolStrategy: string;
  combos: MuseCombo[];
  onReload: () => Promise<void>;
  onMessage: (m: string) => void;
  onError: (m: string) => void;
}) {
  const [loginJobId, setLoginJobId] = useState("");
  const [comboName, setComboName] = useState("");
  const [comboStrategy, setComboStrategy] = useState("round-robin");
  const [selectedAccIds, setSelectedAccIds] = useState<string[]>([]);

  const startLogin = async () => {
    onError("");
    try {
      const res = await apiFetch<{ job_id: string }>(
        "/api/v1/muse/admin/accounts/login",
        {
          method: "POST",
          body: JSON.stringify({ browser_type: "chrome" }),
        }
      );
      setLoginJobId(res.job_id);
      toast.info("Đã mở trình duyệt đăng nhập muse.ai — hãy đăng nhập, hệ thống tự bắt cookie.");
    } catch (err) {
      onError(err instanceof Error ? err.message : "Không mở được trình duyệt đăng nhập");
    }
  };

  const checkLoginJob = async () => {
    if (!loginJobId) return;
    try {
      const res = await apiFetch<{ status: string; error?: string }>(
        `/api/v1/muse/admin/accounts/login/${loginJobId}`
      );
      if (res.status === "done" || res.status === "succeeded" || res.status === "captured") {
        setLoginJobId("");
        onMessage("Đã lưu tài khoản Muse mới thành công!");
        toast.success("Đã lưu tài khoản Muse!");
        await onReload();
      } else if (res.status === "failed" || res.error) {
        setLoginJobId("");
        onError(res.error || "Phiên đăng nhập thất bại");
      } else {
        toast.info(`Trạng thái đăng nhập: ${res.status}`);
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : "Lỗi kiểm tra phiên đăng nhập");
    }
  };

  const changePoolStrategy = async (strategy: string) => {
    try {
      await apiFetch("/api/v1/muse/admin/pool", {
        method: "PATCH",
        body: JSON.stringify({ strategy }),
      });
      toast.success(`Đã đổi chiến lược Pool sang ${strategy}.`);
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Lỗi đổi chiến lược Pool");
    }
  };

  const createCombo = async (e: React.FormEvent) => {
    e.preventDefault();
    onError("");
    try {
      await apiFetch("/api/v1/muse/admin/combos", {
        method: "POST",
        body: JSON.stringify({
          name: comboName,
          account_ids: selectedAccIds,
          strategy: comboStrategy,
          kind: "video",
        }),
      });
      setComboName("");
      setSelectedAccIds([]);
      toast.success("Đã tạo Combo tài khoản Muse mới.");
      await onReload();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Không thể tạo Combo");
    }
  };

  return (
    <div className="space-y-4">
      <Card className="space-y-3.5">
        <CardTitleRow>
          <SectionHeading>
            Tài Khoản Muse &amp; Chiến Lược Xoay Vòng Pool ({accounts.length} tài khoản)
          </SectionHeading>
          <div className="flex flex-wrap items-center gap-2">
            <SelectBox
              aria-label="Chiến lược xoay vòng tài khoản"
              value={poolStrategy}
              onChange={(e) => void changePoolStrategy(e.target.value)}
              className="w-48"
            >
              <option value="round-robin">Round-Robin (Chia đều)</option>
              <option value="fallback">Fallback (Ưu tiên nối tiếp)</option>
              <option value="fusion">Fusion (Đua tốc độ — tốn quota)</option>
            </SelectBox>
            <Button type="button" size="sm" onClick={() => void startLogin()}>
              <UserPlus className="w-3.5 h-3.5" /> Đăng nhập thêm tài khoản
            </Button>
            {loginJobId && (
              <Button
                type="button"
                size="sm"
                variant="emerald"
                onClick={() => void checkLoginJob()}
              >
                <RefreshCw className="w-3.5 h-3.5" /> Kiểm tra phiên đăng nhập
              </Button>
            )}
          </div>
        </CardTitleRow>

        {accounts.length === 0 ? (
          <div className="text-[13px] text-[var(--text-muted)]">
            Chưa có tài khoản Muse nào trong Pool cục bộ. Hãy bấm &ldquo;Đăng nhập thêm tài khoản&rdquo; để bắt đầu chạy đa luồng (2 luồng render / tài khoản).
          </div>
        ) : (
          <div className="divide-y divide-[var(--border-subtle)]">
            {accounts.map((acc) => (
              <div
                key={acc.id}
                className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-[13px]"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <strong className="text-[var(--text-primary)]">{acc.name}</strong>
                  <Badge
                    tone={
                      acc.status === "ready"
                        ? "emerald"
                        : acc.status === "cooldown"
                          ? "amber"
                          : "neutral"
                    }
                  >
                    {acc.status}
                  </Badge>
                  {acc.proxy && <Badge tone="sky">{acc.proxy}</Badge>}
                  {acc.cooldown_remaining_ms > 0 && (
                    <span className="text-[12px] text-[var(--st-amber-tx)] tabular-nums">
                      Nghỉ còn {Math.ceil(acc.cooldown_remaining_ms / 60000)} phút
                    </span>
                  )}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={async () => {
                      const r = await apiFetch<{ valid: boolean }>(
                        `/api/v1/muse/admin/accounts/${acc.id}/test`,
                        { method: "POST" }
                      );
                      toast.info(
                        r.valid
                          ? `Tài khoản ${acc.name} đang LIVE!`
                          : `Tài khoản ${acc.name} cần đăng nhập lại.`
                      );
                      await onReload();
                    }}
                  >
                    Kiểm tra Live
                  </Button>
                  {acc.status === "cooldown" && (
                    <Button
                      type="button"
                      size="sm"
                      variant="amber"
                      onClick={async () => {
                        await apiFetch(`/api/v1/muse/admin/accounts/${acc.id}`, {
                          method: "PATCH",
                          body: JSON.stringify({ reset_cooldown: true }),
                        });
                        await onReload();
                      }}
                    >
                      Xóa Cooldown
                    </Button>
                  )}
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={async () => {
                      await apiFetch(
                        `/api/v1/muse/admin/accounts/${acc.id}/open-browser`,
                        { method: "POST", body: JSON.stringify({}) }
                      );
                      toast.info("Đã mở trình duyệt của tài khoản trên máy.");
                    }}
                  >
                    <ExternalLink className="w-3.5 h-3.5" /> Mở Chrome
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={async () => {
                      await apiFetch(`/api/v1/muse/admin/accounts/${acc.id}`, {
                        method: "DELETE",
                      });
                      await onReload();
                    }}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="space-y-3.5">
        <SectionHeading>Combo Nhóm Tài Khoản ({combos.length})</SectionHeading>
        <form onSubmit={createCombo} className="grid md:grid-cols-3 gap-3">
          <div>
            <FieldLabel htmlFor="cb-name">Tên Combo (dùng làm tên Model)</FieldLabel>
            <TextInput
              id="cb-name"
              required
              value={comboName}
              onChange={(e) => setComboName(e.target.value)}
              placeholder="VD: muse-fast-pool"
            />
          </div>
          <div>
            <FieldLabel htmlFor="cb-strat">Chiến lược</FieldLabel>
            <SelectBox
              id="cb-strat"
              value={comboStrategy}
              onChange={(e) => setComboStrategy(e.target.value)}
            >
              <option value="round-robin">Round-Robin</option>
              <option value="fallback">Fallback</option>
              <option value="fusion">Fusion</option>
            </SelectBox>
          </div>
          <div className="flex items-end">
            <Button type="submit" variant="secondary">
              <Plus className="w-4 h-4" /> Tạo Combo
            </Button>
          </div>
          {accounts.length > 0 && (
            <div className="md:col-span-3 flex flex-wrap gap-2">
              {accounts.map((a) => {
                const picked = selectedAccIds.includes(a.id);
                return (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() =>
                      setSelectedAccIds((prev) =>
                        picked ? prev.filter((x) => x !== a.id) : [...prev, a.id]
                      )
                    }
                    className={`rounded-[8px] border px-2.5 py-1 text-[12px] cursor-pointer ${
                      picked
                        ? "border-[var(--c-bd)] bg-[var(--c-soft)] text-[var(--c-tx)] font-semibold"
                        : "border-[var(--border-subtle)] bg-[var(--bg-elevated)] text-[var(--text-secondary)]"
                    }`}
                  >
                    {a.name}
                  </button>
                );
              })}
            </div>
          )}
        </form>

        {combos.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {combos.map((c) => (
              <div
                key={c.id}
                className="inline-flex items-center gap-2 rounded-[9px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3 py-1.5 text-[12.5px]"
              >
                <span className="font-semibold text-[var(--text-primary)]">{c.name}</span>
                <Badge tone="neutral">{c.strategy}</Badge>
                <button
                  type="button"
                  aria-label={`Xóa combo ${c.name}`}
                  onClick={async () => {
                    await apiFetch(`/api/v1/muse/admin/combos/${c.id}`, {
                      method: "DELETE",
                    });
                    await onReload();
                  }}
                  className="text-[var(--text-muted)] hover:text-[var(--st-rose-tx)] cursor-pointer"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
