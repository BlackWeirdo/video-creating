"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  CheckCircle2,
  Cpu,
  Eye,
  EyeOff,
  KeyRound,
  Layers,
  Rocket,
  RotateCcw,
  Volume2,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace, Workspace } from "@/lib/api";
import { PageHeader, PipelineStepItem } from "@/components/vc/PageHeader";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextInput } from "@/components/ui/form-controls";

interface OnboardingStatus {
  wizard_completed: boolean;
  runtime: {
    ffmpeg_ready: boolean;
    ffprobe_ready: boolean;
    node_ready: boolean;
    ytdlp_ready: boolean;
    ffmpeg_path: string;
    node_path: string;
  };
  workspace_count: number;
  active_workspace_id: number;
  active_workspace: Workspace | null;
  configured_secrets: string[];
  key_pool_count: number;
  connected_channels_count: number;
  defaults: {
    role: string;
    daily_usd: number;
    api_fallback: string;
    timezone: string;
    vi_provider: string;
    vi_voice: string;
  };
}

export default function WelcomeWizardPage() {
  const { refreshWorkspaces, activateWorkspace } = useWorkspace();
  const [step, setStep] = useState(1);
  const [status, setStatus] = useState<OnboardingStatus | null>(null);

  const [wsMode, setWsMode] = useState<"update" | "create">("update");
  const [wsName, setWsName] = useState("");
  const [wsNiche, setWsNiche] = useState("general");
  const [wsPolicy, setWsPolicy] =
    useState<Workspace["content_policy"]>("strict_footage");
  const [wsApproval, setWsApproval] =
    useState<Workspace["approval_mode"]>("single");
  const [wsRatio, setWsRatio] =
    useState<Workspace["default_aspect_ratio"]>("9:16");

  const [dailyUsd, setDailyUsd] = useState(5.0);
  const [apiFallback, setApiFallback] = useState("ask");
  const [geminiKey, setGeminiKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [apifyToken, setApifyToken] = useState("");
  const [showKeys, setShowKeys] = useState(false);

  const [viProvider, setViProvider] = useState("edge");
  const [viVoice, setViVoice] = useState("vi-VN-HoaiMyNeural-Female");
  const [timezone, setTimezone] = useState("Asia/Ho_Chi_Minh");

  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const s = await apiFetch<OnboardingStatus>("/api/v1/onboarding/status");
      setStatus(s);
      if (s.active_workspace) {
        setWsName(s.active_workspace.name);
        setWsNiche(s.active_workspace.niche);
        setWsPolicy(s.active_workspace.content_policy);
        setWsApproval(s.active_workspace.approval_mode);
        setWsRatio(s.active_workspace.default_aspect_ratio);
      }
      setDailyUsd(s.defaults.daily_usd ?? 5.0);
      setApiFallback(s.defaults.api_fallback || "ask");
      setTimezone(s.defaults.timezone || "Asia/Ho_Chi_Minh");
      setViProvider(s.defaults.vi_provider || "edge");
      setViVoice(s.defaults.vi_voice || "vi-VN-HoaiMyNeural-Female");
      setErr("");
    } catch (e) {
      setErr(
        e instanceof Error ? e.message : "Không tải được trạng thái thiết lập"
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const finishWizard = async () => {
    setSaving(true);
    setErr("");
    setMsg("");
    try {
      const secrets: Record<string, string> = {};
      if (geminiKey.trim()) secrets.GEMINI_API_KEY = geminiKey.trim();
      if (anthropicKey.trim()) secrets.ANTHROPIC_API_KEY = anthropicKey.trim();
      if (apifyToken.trim()) secrets.APIFY_API_TOKEN = apifyToken.trim();

      const res = await apiFetch<OnboardingStatus>(
        "/api/v1/onboarding/complete",
        {
          method: "POST",
          body: JSON.stringify({
            workspace: {
              mode: wsMode,
              id: status?.active_workspace_id || 1,
              name: wsName,
              niche: wsNiche,
              content_policy: wsPolicy,
              approval_mode: wsApproval,
              default_aspect_ratio: wsRatio,
            },
            daily_usd: dailyUsd,
            api_fallback: apiFallback,
            timezone,
            vi_provider: viProvider,
            vi_voice: viVoice,
            secrets,
          }),
        }
      );
      setStatus(res);
      await refreshWorkspaces();
      if (res.active_workspace_id) {
        await activateWorkspace(res.active_workspace_id);
      }
      setGeminiKey("");
      setAnthropicKey("");
      setApifyToken("");
      if (typeof window !== "undefined") {
        window.dispatchEvent(new Event("vc:onboarding-updated"));
      }
      const ok =
        "Hoàn tất thiết lập ban đầu! Bạn có thể bắt đầu sản xuất video ngay.";
      setMsg(ok);
      toast.success(ok);
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi hoàn tất hướng dẫn thiết lập");
    } finally {
      setSaving(false);
    }
  };

  const steps: PipelineStepItem[] = [
    {
      title: "1. Kiểm tra Máy",
      subtitle: "FFmpeg, Node, yt-dlp",
      state: step > 1 ? "done" : step === 1 ? "active" : "idle",
    },
    {
      title: "2. Thương hiệu",
      subtitle: "Workspace & Chính sách",
      state: step > 2 ? "done" : step === 2 ? "active" : "idle",
    },
    {
      title: "3. Khóa AI & Quỹ",
      subtitle: "Mã hóa cục bộ",
      state: step > 3 ? "done" : step === 3 ? "active" : "idle",
    },
    {
      title: "4. Giọng & Hoàn tất",
      subtitle: "Tiếng Việt & Múi giờ",
      state: status?.wizard_completed && step === 4 ? "done" : step === 4 ? "active" : "idle",
    },
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <PageHeader
        icon={<Rocket className="w-5 h-5" />}
        title="Hướng Dẫn Thiết Lập Nhanh — Video Creator V2"
        description="Kiểm tra công cụ dựng phim đóng gói sẵn trên máy, tạo Workspace đầu tiên, mã hóa khóa API và chọn giọng đọc mặc định."
        steps={steps}
        actions={
          status?.wizard_completed ? (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={async () => {
                const s = await apiFetch<OnboardingStatus>(
                  "/api/v1/onboarding/reset",
                  { method: "POST" }
                );
                setStatus(s);
                if (typeof window !== "undefined") {
                  window.dispatchEvent(new Event("vc:onboarding-updated"));
                }
                setStep(1);
              }}
            >
              <RotateCcw className="w-3.5 h-3.5" /> Chạy lại từ bước 1
            </Button>
          ) : undefined
        }
      />

      {/* Clickable Step Tabs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        {[
          { id: 1, title: "Bước 1: Kiểm tra Máy", icon: Cpu },
          { id: 2, title: "Bước 2: Workspace", icon: Layers },
          { id: 3, title: "Bước 3: Khóa AI", icon: KeyRound },
          { id: 4, title: "Bước 4: Giọng & Xong", icon: Volume2 },
        ].map((item) => {
          const Icon = item.icon;
          const active = step === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setStep(item.id)}
              className={`flex items-center gap-2 rounded-[10px] border px-3 py-2.5 text-left text-[13px] cursor-pointer transition-colors ${
                active
                  ? "border-[var(--c-bd)] bg-[var(--c-soft)] text-[var(--c-tx)] font-bold"
                  : "border-[var(--border-subtle)] bg-[var(--bg-card)] text-[var(--text-secondary)] hover:border-[var(--c-bd)]"
              }`}
            >
              <Icon className="w-4 h-4 shrink-0" />
              <span className="truncate">{item.title}</span>
            </button>
          );
        })}
      </div>

      {msg && (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-3 rounded-[11px] border border-[var(--st-emerald-bd)] bg-[var(--st-emerald-bg)] px-4 py-3 text-[13.5px] text-[var(--st-emerald-tx)]"
        >
          <span className="inline-flex items-center gap-2 font-semibold">
            <CheckCircle2 className="w-4 h-4" /> {msg}
          </span>
          <Button asChild size="sm" variant="emerald">
            <Link href="/">Vào Tổng quan →</Link>
          </Button>
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

      {step === 1 && status && (
        <Card tinted className="space-y-4">
          <SectionHeading>
            Kiểm tra Công cụ Đóng Gói Cục Bộ trên Máy Trạm
          </SectionHeading>
          <div className="grid md:grid-cols-2 gap-3">
            {[
              {
                name: "Bộ kết xuất video FFmpeg",
                ok: status.runtime.ffmpeg_ready,
                note: status.runtime.ffmpeg_path,
              },
              {
                name: "Bộ đo kiểm âm lượng FFprobe",
                ok: status.runtime.ffprobe_ready,
                note: "Đo thời lượng & chuẩn -14 LUFS",
              },
              {
                name: "Môi trường giao diện Node 24 LTS",
                ok: status.runtime.node_ready,
                note: status.runtime.node_path || "Next.js 15 & Remotion",
              },
              {
                name: "Trình tải nguồn tham khảo yt-dlp",
                ok: status.runtime.ytdlp_ready,
                note: "Hỗ trợ xu hướng & nguồn Việt hóa",
              },
            ].map((chk) => (
              <div
                key={chk.name}
                className="flex items-center justify-between gap-2 rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5"
              >
                <div className="min-w-0">
                  <div className="text-[13.5px] font-bold text-[var(--text-primary)]">
                    {chk.name}
                  </div>
                  <div className="truncate text-[12px] text-[var(--text-muted)]">
                    {chk.note}
                  </div>
                </div>
                <Badge tone={chk.ok ? "emerald" : "amber"}>
                  {chk.ok ? "Sẵn sàng" : "Thiếu"}
                </Badge>
              </div>
            ))}
          </div>
          <div className="flex justify-end">
            <Button type="button" onClick={() => setStep(2)}>
              Tiếp tục: Thương hiệu →
            </Button>
          </div>
        </Card>
      )}

      {step === 2 && (
        <Card tinted className="space-y-4">
          <SectionHeading>
            Cấu hình Thương Hiệu Đầu Tiên &amp; Chính sách Nội dung
          </SectionHeading>
          <div className="flex flex-wrap gap-4 text-[13px]">
            <label className="inline-flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                checked={wsMode === "update"}
                onChange={() => setWsMode("update")}
                className="accent-[var(--c-solid)]"
              />
              <span>Cập nhật Workspace hiện tại</span>
            </label>
            <label className="inline-flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                checked={wsMode === "create"}
                onChange={() => {
                  setWsMode("create");
                  setWsName("");
                }}
                className="accent-[var(--c-solid)]"
              />
              <span>Tạo mới một Workspace riêng</span>
            </label>
          </div>

          <div className="grid md:grid-cols-2 gap-3.5">
            <div>
              <FieldLabel htmlFor="wz-name">Tên thương hiệu / Dự án</FieldLabel>
              <TextInput
                id="wz-name"
                value={wsName}
                onChange={(e) => setWsName(e.target.value)}
                placeholder="VD: Trang Sức Bạc S925"
              />
            </div>
            <div>
              <FieldLabel htmlFor="wz-niche">Ngành hàng / Chủ đề</FieldLabel>
              <TextInput
                id="wz-niche"
                value={wsNiche}
                onChange={(e) => setWsNiche(e.target.value)}
              />
            </div>
            <div>
              <FieldLabel htmlFor="wz-policy">Chính sách Nội dung</FieldLabel>
              <SelectBox
                id="wz-policy"
                value={wsPolicy}
                onChange={(e) =>
                  setWsPolicy(e.target.value as Workspace["content_policy"])
                }
              >
                <option value="strict_footage">
                  Strict Footage (100% cảnh quay sản phẩm thật)
                </option>
                <option value="hybrid_remix">
                  Hybrid Remix (Việt hóa + chèn cảnh quay thật)
                </option>
                <option value="full_ai">
                  Full AI (Truyện, Bản tin, Podcast, Việt hóa)
                </option>
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="wz-ratio">
                Tỷ lệ khung hình &amp; Chế độ duyệt
              </FieldLabel>
              <div className="grid grid-cols-2 gap-2">
                <SelectBox
                  id="wz-ratio"
                  value={wsRatio}
                  onChange={(e) =>
                    setWsRatio(
                      e.target.value as Workspace["default_aspect_ratio"]
                    )
                  }
                >
                  <option value="9:16">9:16 Dọc</option>
                  <option value="16:9">16:9 Ngang</option>
                  <option value="1:1">1:1 Vuông</option>
                </SelectBox>
                <SelectBox
                  aria-label="Chế độ duyệt mặc định"
                  value={wsApproval}
                  onChange={(e) =>
                    setWsApproval(e.target.value as Workspace["approval_mode"])
                  }
                >
                  <option value="single">Duyệt từng bài</option>
                  <option value="bulk">Duyệt hàng loạt</option>
                  <option value="autopilot">Tự động đăng</option>
                </SelectBox>
              </div>
            </div>
          </div>

          <div className="flex justify-between">
            <Button type="button" variant="secondary" onClick={() => setStep(1)}>
              ← Quay lại
            </Button>
            <Button type="button" onClick={() => setStep(3)}>
              Tiếp tục: Khóa AI →
            </Button>
          </div>
        </Card>
      )}

      {step === 3 && (
        <Card tinted className="space-y-4">
          <div className="flex items-center justify-between gap-2">
            <SectionHeading>
              Mã hóa Khóa API &amp; Hạn mức Chi tiêu Ngày
            </SectionHeading>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setShowKeys((v) => !v)}
            >
              {showKeys ? (
                <>
                  <EyeOff className="w-4 h-4" /> Ẩn khóa
                </>
              ) : (
                <>
                  <Eye className="w-4 h-4" /> Hiện khóa
                </>
              )}
            </Button>
          </div>

          <p className="text-[12.5px] text-[var(--text-muted)]">
            Khóa đã lưu trên máy:{" "}
            {(status?.configured_secrets || []).join(", ") ||
              "Chưa đặt (có thể bỏ qua và dùng mô hình nội bộ trên CPU)."}
          </p>

          <div className="grid md:grid-cols-2 gap-3.5">
            <div>
              <FieldLabel htmlFor="wz-usd">Hạn mức chi phí API / ngày (USD)</FieldLabel>
              <TextInput
                id="wz-usd"
                type="number"
                step="0.5"
                value={dailyUsd}
                onChange={(e) => setDailyUsd(Number(e.target.value))}
                className="tabular-nums"
              />
            </div>
            <div>
              <FieldLabel htmlFor="wz-fb">Chế độ vượt gói thuê bao</FieldLabel>
              <SelectBox
                id="wz-fb"
                value={apiFallback}
                onChange={(e) => setApiFallback(e.target.value)}
              >
                <option value="ask">Hỏi xác nhận trước khi gọi API trả phí</option>
                <option value="auto">Tự động chuyển sang API khi hết hạn mức</option>
                <option value="never">Không bao giờ gọi API ngoài gói</option>
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="wz-gem">Khóa Gemini API (tùy chọn)</FieldLabel>
              <TextInput
                id="wz-gem"
                type={showKeys ? "text" : "password"}
                value={geminiKey}
                onChange={(e) => setGeminiKey(e.target.value)}
                placeholder="AIza..."
              />
            </div>
            <div>
              <FieldLabel htmlFor="wz-ant">Khóa Anthropic Claude (tùy chọn)</FieldLabel>
              <TextInput
                id="wz-ant"
                type={showKeys ? "text" : "password"}
                value={anthropicKey}
                onChange={(e) => setAnthropicKey(e.target.value)}
                placeholder="sk-ant-..."
              />
            </div>
            <div className="md:col-span-2">
              <FieldLabel htmlFor="wz-apf">
                Mã Apify (quét xu hướng mạng xã hội, tùy chọn)
              </FieldLabel>
              <TextInput
                id="wz-apf"
                type={showKeys ? "text" : "password"}
                value={apifyToken}
                onChange={(e) => setApifyToken(e.target.value)}
                placeholder="apify_api_..."
              />
            </div>
          </div>

          <div className="flex justify-between">
            <Button type="button" variant="secondary" onClick={() => setStep(2)}>
              ← Quay lại
            </Button>
            <Button type="button" onClick={() => setStep(4)}>
              Tiếp tục: Giọng đọc →
            </Button>
          </div>
        </Card>
      )}

      {step === 4 && (
        <Card tinted className="space-y-4">
          <SectionHeading>
            Giọng Đọc Tiếng Việt Mặc Định &amp; Múi Giờ Lịch Đăng
          </SectionHeading>
          <div className="grid md:grid-cols-3 gap-3.5">
            <div>
              <FieldLabel htmlFor="wz-prov">Bộ tổng hợp giọng đọc</FieldLabel>
              <SelectBox
                id="wz-prov"
                value={viProvider}
                onChange={(e) => setViProvider(e.target.value)}
              >
                <option value="edge">Edge TTS (Trực tuyến miễn phí)</option>
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="wz-voice">Giọng đọc Tiếng Việt</FieldLabel>
              <SelectBox
                id="wz-voice"
                value={viVoice}
                onChange={(e) => setViVoice(e.target.value)}
              >
                <option value="vi-VN-HoaiMyNeural-Female">
                  Hoài My (Nữ tự nhiên)
                </option>
                <option value="vi-VN-NamMinhNeural-Male">
                  Nam Minh (Nam trầm rõ)
                </option>
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="wz-tz">Múi giờ lịch đăng</FieldLabel>
              <TextInput
                id="wz-tz"
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
              />
            </div>
          </div>

          <div className="flex justify-between pt-2">
            <Button type="button" variant="secondary" onClick={() => setStep(3)}>
              ← Quay lại
            </Button>
            <Button
              type="button"
              variant="emerald"
              disabled={saving}
              onClick={() => void finishWizard()}
            >
              <Rocket className="w-4 h-4" />{" "}
              {saving ? "Đang lưu cấu hình..." : "Hoàn Tất Thiết Lập"}
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}
