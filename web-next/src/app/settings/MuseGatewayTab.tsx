"use client";

import React, { useState } from "react";
import {
  Download,
  Link2,
  Play,
  RefreshCw,
  Save,
  ShieldAlert,
  Square,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch, apiFetchBlob } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import type { MuseCombo, MusePoolAccount, MuseStatus } from "@/app/muse/types";
import { AccountsAndPoolSection } from "@/app/settings/_muse/AccountsAndPoolSection";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  SwitchToggle,
  TextInput,
} from "@/components/ui/form-controls";

export interface MuseGatewaySettingsShape {
  enabled: boolean;
  mode: "local_sidecar" | "remote";
  base_url: string;
  max_parallel: number;
  renders_per_account: number;
  daily_cap_video_per_account: number;
  remote_hardened_confirmed: boolean;
  include_in_vcx_backup: boolean;
}

export function MuseGatewayTab({
  initialConfig,
  onReloadParent,
  onMessage,
  onError,
}: {
  initialConfig: MuseGatewaySettingsShape;
  onReloadParent: () => Promise<void>;
  onMessage: (m: string) => void;
  onError: (m: string) => void;
}) {
  const [cfg, setCfg] = useState<MuseGatewaySettingsShape>(initialConfig);
  const [pairInfo, setPairInfo] = useState<{
    pair_id: string;
    code: string;
    approve_url: string;
  } | null>(null);

  const { data: bundle, reload } = useApiQuery(
    async (signal) => {
      const status = await apiFetch<MuseStatus>("/api/v1/muse/status", { signal });
      let accounts: MusePoolAccount[] = [];
      let poolStrategy = "round-robin";
      let combos: MuseCombo[] = [];
      if (status.online && status.mode === "local_sidecar" && status.hardened) {
        const [accRes, poolRes, cbRes] = await Promise.all([
          apiFetch<{ accounts: MusePoolAccount[] }>("/api/v1/muse/admin/accounts", {
            signal,
          }).catch(() => ({ accounts: [] })),
          apiFetch<{ strategy: string }>("/api/v1/muse/admin/pool", {
            signal,
          }).catch(() => ({ strategy: "round-robin" })),
          apiFetch<{ combos: MuseCombo[] }>("/api/v1/muse/admin/combos", {
            signal,
          }).catch(() => ({ combos: [] })),
        ]);
        accounts = accRes.accounts || [];
        poolStrategy = poolRes.strategy || "round-robin";
        combos = cbRes.combos || [];
      }
      return { status, accounts, poolStrategy, combos };
    },
    [],
    { fallbackError: "Không đọc được trạng thái Muse Gateway" }
  );

  const status = bundle?.status;

  const saveMuseSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    onError("");
    try {
      await apiFetch("/api/v1/settings", {
        method: "PUT",
        body: JSON.stringify({ muse_gateway: cfg }),
      });
      const m = "Đã lưu cấu hình kết nối & điều phối Muse Gateway.";
      onMessage(m);
      toast.success(m);
      await Promise.all([reload(), onReloadParent()]);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Lỗi lưu cấu hình Muse Gateway");
    }
  };

  const startPairing = async () => {
    onError("");
    try {
      const res = await apiFetch<{
        pair_id: string;
        code: string;
        approve_url: string;
      }>("/api/v1/muse/pair", { method: "POST", body: JSON.stringify({}) });
      setPairInfo(res);
      toast.info(`Mã ghép nối: ${res.code} — bấm Mở trang xác nhận rồi chọn Allow.`);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Không thể bắt đầu ghép nối");
    }
  };

  const pollPairing = async () => {
    if (!pairInfo) return;
    try {
      const res = await apiFetch<{ status: string; key_saved: boolean }>(
        `/api/v1/muse/pair/${pairInfo.pair_id}`
      );
      if (res.key_saved) {
        setPairInfo(null);
        const m = "Đã ghép nối & lưu khóa API Muse Gateway vào kho DPAPI an toàn!";
        onMessage(m);
        toast.success(m);
        await reload();
      } else {
        toast.info(`Trạng thái ghép nối: ${res.status} (hãy bấm Allow trên trang Gateway)`);
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : "Lỗi kiểm tra ghép nối");
    }
  };

  const downloadUsageCsv = async () => {
    try {
      const blob = await apiFetchBlob("/api/v1/muse/admin/usage.csv?range=30d");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "muse-usage-30d.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Không tải được báo cáo CSV");
    }
  };

  return (
    <div className="space-y-4">
      {status?.unsafe_error && (
        <div
          role="alert"
          className="rounded-[12px] border border-[var(--st-rose-bd)] bg-[var(--st-rose-bg)] p-3.5 text-[13px] text-[var(--st-rose-tx)] flex items-start gap-2.5"
        >
          <ShieldAlert className="w-5 h-5 shrink-0 mt-0.5" />
          <div>
            <div className="font-bold">Cảnh báo bảo mật — Đã chặn kết nối Gateway chưa vá</div>
            <div>{status.unsafe_error}</div>
          </div>
        </div>
      )}

      <Card tinted className="space-y-4">
        <CardTitleRow>
          <SectionHeading>Kết Nối Muse Gateway (`vc-hardened`) &amp; Sidecar Cục Bộ</SectionHeading>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={status?.online && status?.hardened ? "emerald" : "neutral"}>
              {status?.online
                ? status.hardened
                  ? `Online • vc-hardened ${status.version}`
                  : "Chưa vá bảo mật"
                : "Đang tắt / Offline"}
            </Badge>
            <Badge tone={status?.paired ? "sky" : "amber"}>
              {status?.paired ? "Đã lưu khóa DPAPI" : "Chưa ghép nối khóa"}
            </Badge>
          </div>
        </CardTitleRow>

        <div className="flex flex-wrap gap-2">
          {cfg.mode === "local_sidecar" && (
            <>
              <Button
                type="button"
                size="sm"
                variant="emerald"
                onClick={async () => {
                  try {
                    await apiFetch("/api/v1/muse/sidecar/start", { method: "POST" });
                    toast.success("Sidecar Muse Gateway đã sẵn sàng.");
                    await reload();
                  } catch (e2) {
                    onError(e2 instanceof Error ? e2.message : "Lỗi khởi chạy Sidecar");
                  }
                }}
              >
                <Play className="w-3.5 h-3.5" /> Khởi động / Gắn Sidecar
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={async () => {
                  await apiFetch("/api/v1/muse/sidecar/stop", { method: "POST" });
                  await reload();
                }}
              >
                <Square className="w-3.5 h-3.5" /> Dừng Sidecar
              </Button>
            </>
          )}
          <Button type="button" size="sm" onClick={() => void startPairing()}>
            <Link2 className="w-3.5 h-3.5" /> Kết nối 1 chạm (Pairing)
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => void reload()}>
            <RefreshCw className="w-3.5 h-3.5" /> Làm mới
          </Button>
        </div>

        {pairInfo && (
          <div className="rounded-[10px] border border-[var(--c-bd)] bg-[var(--bg-elevated)] p-3.5 flex flex-wrap items-center justify-between gap-3 text-[13px]">
            <div>
              Mã xác nhận ghép nối: <strong className="font-mono text-[15px]">{pairInfo.code}</strong>
            </div>
            <div className="flex gap-2">
              <Button asChild size="sm" variant="secondary">
                <a href={pairInfo.approve_url} target="_blank" rel="noreferrer">
                  1. Mở trang Allow trên Gateway
                </a>
              </Button>
              <Button type="button" size="sm" variant="emerald" onClick={() => void pollPairing()}>
                2. Hoàn tất lưu khóa
              </Button>
            </div>
          </div>
        )}

        <form onSubmit={saveMuseSettings} className="space-y-3.5">
          <div className="flex items-center gap-2.5">
            <SwitchToggle
              id="mg-enabled"
              checked={cfg.enabled}
              onCheckedChange={(v) => setCfg((p) => ({ ...p, enabled: v }))}
            />
            <label htmlFor="mg-enabled" className="text-[13.5px] font-semibold text-[var(--text-primary)]">
              Bật bộ điều phối Muse Gateway đa luồng (Video, Ảnh dự phòng, TTS &amp; Storyboard)
            </label>
          </div>

          <div className="grid md:grid-cols-4 gap-3">
            <div>
              <FieldLabel htmlFor="mg-mode">Chế độ vận hành</FieldLabel>
              <SelectBox
                id="mg-mode"
                value={cfg.mode}
                onChange={(e) =>
                  setCfg((p) => ({
                    ...p,
                    mode: e.target.value as "local_sidecar" | "remote",
                  }))
                }
              >
                <option value="local_sidecar">Local Sidecar (127.0.0.1)</option>
                <option value="remote">Remote / Tailscale HTTPS</option>
              </SelectBox>
            </div>
            <div className="md:col-span-2">
              <FieldLabel htmlFor="mg-url">Địa chỉ Muse Gateway</FieldLabel>
              <TextInput
                id="mg-url"
                value={cfg.base_url}
                onChange={(e) => setCfg((p) => ({ ...p, base_url: e.target.value }))}
                placeholder="http://127.0.0.1:1412"
              />
            </div>
            <div>
              <FieldLabel htmlFor="mg-par">Trần luồng song song tối đa</FieldLabel>
              <TextInput
                id="mg-par"
                type="number"
                min={1}
                max={64}
                value={cfg.max_parallel}
                onChange={(e) =>
                  setCfg((p) => ({ ...p, max_parallel: Number(e.target.value) }))
                }
                className="tabular-nums"
              />
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <FieldLabel htmlFor="mg-cap-vid">
                Trần an toàn Video / Tài khoản / Ngày (bảo vệ tài khoản khỏi khóa)
              </FieldLabel>
              <TextInput
                id="mg-cap-vid"
                type="number"
                min={1}
                max={200}
                value={cfg.daily_cap_video_per_account}
                onChange={(e) =>
                  setCfg((p) => ({
                    ...p,
                    daily_cap_video_per_account: Number(e.target.value),
                  }))
                }
                className="tabular-nums"
              />
            </div>
            <div className="flex items-center gap-2.5 pt-5">
              <SwitchToggle
                id="mg-vcx"
                checked={cfg.include_in_vcx_backup}
                onCheckedChange={(v) =>
                  setCfg((p) => ({ ...p, include_in_vcx_backup: v }))
                }
              />
              <label htmlFor="mg-vcx" className="text-[12.5px] text-[var(--text-secondary)]">
                Nhúng trạng thái tài khoản &amp; combo Muse (mã hóa Fernet) khi xuất gói .vcx
              </label>
            </div>
          </div>

          {cfg.mode === "remote" && (
            <div className="flex items-center gap-2.5 rounded-[10px] border border-[var(--st-amber-bd)] bg-[var(--st-amber-bg)] px-3.5 py-2.5">
              <SwitchToggle
                id="mg-rem-ok"
                checked={cfg.remote_hardened_confirmed}
                onCheckedChange={(v) =>
                  setCfg((p) => ({ ...p, remote_hardened_confirmed: v }))
                }
              />
              <label htmlFor="mg-rem-ok" className="text-[12.5px] text-[var(--st-amber-tx)] font-medium">
                Tôi xác nhận máy chủ Muse Gateway từ xa đang chạy bản fork vc-hardened (MUSE_CMD_MODE=off)
              </label>
            </div>
          )}

          <div className="flex flex-wrap gap-2.5">
            <Button type="submit">
              <Save className="w-4 h-4" /> Lưu Cấu Hình Muse Gateway
            </Button>
            {cfg.mode === "local_sidecar" && status?.online && (
              <>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => void downloadUsageCsv()}
                >
                  <Download className="w-4 h-4" /> Xuất Thống Kê CSV (30 ngày)
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={async () => {
                    await apiFetch("/api/v1/muse/admin/cleanup", {
                      method: "POST",
                      body: JSON.stringify({ scope: "finished" }),
                    });
                    toast.success("Đã dọn tệp tạm trên Muse Gateway.");
                  }}
                >
                  <Trash2 className="w-4 h-4" /> Dọn Tệp Tạm Gateway
                </Button>
              </>
            )}
          </div>
        </form>
      </Card>

      {cfg.mode === "local_sidecar" && status?.online && status?.hardened && (
        <AccountsAndPoolSection
          accounts={bundle?.accounts || []}
          poolStrategy={bundle?.poolStrategy || "round-robin"}
          combos={bundle?.combos || []}
          onReload={reload}
          onMessage={onMessage}
          onError={onError}
        />
      )}
    </div>
  );
}
