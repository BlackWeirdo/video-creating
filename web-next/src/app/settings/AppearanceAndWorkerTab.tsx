"use client";

import React, { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Monitor, Moon, RotateCcw, Save, Sun } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { STORAGE_KEYS } from "@/config/navigation";
import { VoiceOption } from "@/app/settings/types";
import { Card, CardTitleRow, SectionHeading } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  SwitchToggle,
  TextInput,
} from "@/components/ui/form-controls";

export function AppearanceAndWorkerTab({
  ioConc,
  setIoConc,
  computeConc,
  setComputeConc,
  dailyUsd,
  setDailyUsd,
  apiFallback,
  setApiFallback,
  timezone,
  setTimezone,
  mirrorBaseUrl,
  viProvider,
  setViProvider,
  viVoice,
  setViVoice,
  catalog,
  onReload,
  onMessage,
  onError,
}: {
  ioConc: number;
  setIoConc: (v: number) => void;
  computeConc: number;
  setComputeConc: (v: number) => void;
  dailyUsd: number;
  setDailyUsd: (v: number) => void;
  apiFallback: string;
  setApiFallback: (v: string) => void;
  timezone: string;
  setTimezone: (v: string) => void;
  mirrorBaseUrl: string;
  viProvider: string;
  setViProvider: (v: string) => void;
  viVoice: string;
  setViVoice: (v: string) => void;
  catalog: VoiceOption[];
  onReload: () => Promise<void>;
  onMessage: (m: string) => void;
  onError: (m: string) => void;
}) {
  const { theme, setTheme } = useTheme();
  const [compactSidebar, setCompactSidebar] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    try {
      setCompactSidebar(localStorage.getItem(STORAGE_KEYS.SIDEBAR_COLLAPSED) === "1");
    } catch {
      // ignore
    }
  }, []);

  const handleToggleCompact = (next: boolean) => {
    setCompactSidebar(next);
    try {
      localStorage.setItem(STORAGE_KEYS.SIDEBAR_COLLAPSED, next ? "1" : "0");
      window.dispatchEvent(new Event("vc:nav-prefs-changed"));
    } catch {
      // ignore
    }
  };

  const resetNavPrefs = () => {
    try {
      localStorage.removeItem(STORAGE_KEYS.FAVORITES);
      localStorage.removeItem(STORAGE_KEYS.CLUSTERS);
      localStorage.removeItem(STORAGE_KEYS.SIDEBAR_COLLAPSED);
      setCompactSidebar(false);
      window.dispatchEvent(new Event("vc:nav-prefs-changed"));
      toast.success("Đã đặt lại mục ghim yêu thích và bố cục thanh bên về mặc định.");
    } catch {
      // ignore
    }
  };

  const saveConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    onError("");
    onMessage("");
    setSaving(true);
    try {
      await Promise.all([
        apiFetch("/api/v1/settings", {
          method: "PUT",
          body: JSON.stringify({
            worker: {
              io_concurrency: ioConc,
              compute_concurrency: computeConc,
            },
            budget: { daily_usd: dailyUsd },
            ai: { policy: { api_fallback: apiFallback } },
            schedule: { timezone },
            models: { mirror_base_url: mirrorBaseUrl.trim() },
          }),
        }),
        apiFetch("/api/v1/voices", {
          method: "PUT",
          body: JSON.stringify({ vi_provider: viProvider, vi_voice: viVoice }),
        }),
      ]);
      const m = "Đã lưu cấu hình Tiến trình nền, Ngân sách AI & Giọng đọc.";
      onMessage(m);
      toast.success(m);
      await onReload();
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Lỗi lưu cấu hình");
    } finally {
      setSaving(false);
    }
  };

  const themeOptions = [
    {
      key: "light",
      title: "Chế độ Sáng",
      desc: "Nền sáng tinh gọn, chữ đậm sắc nét",
      icon: Sun,
    },
    {
      key: "dark",
      title: "Chế độ Tối",
      desc: "Tối rực rỡ kiểu phòng dựng Studio",
      icon: Moon,
    },
    {
      key: "system",
      title: "Theo Windows",
      desc: "Tự động đồng bộ Sáng / Tối theo máy",
      icon: Monitor,
    },
  ] as const;

  return (
    <div className="space-y-4">
      <Card tinted className="space-y-4">
        <CardTitleRow>
          <SectionHeading>Giao diện, Màu sắc &amp; Thanh điều hướng</SectionHeading>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={resetNavPrefs}
          >
            <RotateCcw className="w-3.5 h-3.5" /> Đặt lại mục ghim &amp; cụm menu
          </Button>
        </CardTitleRow>

        <div className="grid sm:grid-cols-3 gap-3">
          {themeOptions.map((opt) => {
            const Icon = opt.icon;
            const active = (theme || "system") === opt.key;
            return (
              <button
                key={opt.key}
                type="button"
                onClick={() => setTheme(opt.key)}
                className={`rounded-[12px] border p-3.5 text-left cursor-pointer transition-all ${
                  active
                    ? "border-[var(--c-bd)] bg-[var(--c-soft)] shadow-[var(--c-glow)]"
                    : "border-[var(--border-subtle)] bg-[var(--bg-elevated)] hover:border-[var(--c-bd)]"
                }`}
              >
                <div className="flex items-center gap-2 text-[14px] font-bold text-[var(--text-primary)]">
                  <Icon className="w-4 h-4 text-[var(--c-icon)]" />
                  <span>{opt.title}</span>
                </div>
                <div className="mt-1 text-[12px] text-[var(--text-muted)]">
                  {opt.desc}
                </div>
              </button>
            );
          })}
        </div>

        <div className="flex items-center justify-between gap-3 rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3.5 py-2.5">
          <div>
            <div className="text-[13.5px] font-semibold text-[var(--text-primary)]">
              Luôn thu gọn thanh bên thành dải Icon (68px)
            </div>
            <div className="text-[12px] text-[var(--text-muted)]">
              Dành tối đa diện tích ngang cho bảng biên tập kịch bản và trình dựng video.
            </div>
          </div>
          <SwitchToggle
            id="pref-compact-sb"
            checked={compactSidebar}
            onCheckedChange={handleToggleCompact}
            aria-label="Luôn thu gọn thanh bên"
          />
        </div>
      </Card>

      <Card>
        <form onSubmit={saveConfig} className="space-y-4">
          <SectionHeading>
            Tiến trình xử lý nền, Ngân sách AI &amp; Giọng đọc mặc định
          </SectionHeading>

          <div className="grid md:grid-cols-3 gap-3">
            <div>
              <FieldLabel htmlFor="cfg-io">
                Số tác vụ tải / đăng đồng thời
              </FieldLabel>
              <TextInput
                id="cfg-io"
                type="number"
                min={1}
                max={16}
                value={ioConc}
                onChange={(e) => setIoConc(Number(e.target.value))}
                className="tabular-nums"
              />
            </div>
            <div>
              <FieldLabel htmlFor="cfg-compute">
                Số luồng xử lý video CPU (khuyên dùng: 1 trên PC 8GB)
              </FieldLabel>
              <TextInput
                id="cfg-compute"
                type="number"
                min={1}
                max={4}
                value={computeConc}
                onChange={(e) => setComputeConc(Number(e.target.value))}
                className="tabular-nums"
              />
            </div>
            <div>
              <FieldLabel htmlFor="cfg-budget">
                Hạn mức chi phí AI mỗi ngày (USD)
              </FieldLabel>
              <TextInput
                id="cfg-budget"
                type="number"
                step="0.5"
                min={0}
                value={dailyUsd}
                onChange={(e) => setDailyUsd(Number(e.target.value))}
                className="tabular-nums"
              />
            </div>
          </div>

          <div className="grid md:grid-cols-3 gap-3">
            <div>
              <FieldLabel htmlFor="cfg-fallback">
                Chế độ dự phòng khi hết gói thuê bao AI
              </FieldLabel>
              <SelectBox
                id="cfg-fallback"
                value={apiFallback}
                onChange={(e) => setApiFallback(e.target.value)}
              >
                <option value="ask">Hỏi xác nhận trước khi chuyển sang API trả phí</option>
                <option value="never">Chỉ dùng gói thuê bao cố định</option>
                <option value="auto">Tự động chuyển sang API Key</option>
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="cfg-tz">Múi giờ lịch đăng</FieldLabel>
              <TextInput
                id="cfg-tz"
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
              />
            </div>
            <div>
              <FieldLabel htmlFor="cfg-voice">
                Giọng đọc Tiếng Việt mặc định
              </FieldLabel>
              <SelectBox
                id="cfg-voice"
                value={`${viProvider}:${viVoice}`}
                onChange={(e) => {
                  const [p, v] = e.target.value.split(":");
                  setViProvider(p);
                  setViVoice(v);
                }}
              >
                {catalog
                  .filter((c) => c.lang === "vi")
                  .map((c) => (
                    <option
                      key={`${c.provider}:${c.voice}`}
                      value={`${c.provider}:${c.voice}`}
                    >
                      {c.label}
                    </option>
                  ))}
              </SelectBox>
            </div>
          </div>

          <Button type="submit" disabled={saving}>
            <Save className="w-4 h-4" />{" "}
            {saving ? "Đang lưu..." : "Lưu Cấu Hình Hệ Thống"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
