"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  CheckCircle2,
  Cpu,
  KeyRound,
  Layers,
  Rocket,
  RotateCcw,
  Volume2,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace, Workspace } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import type { OnboardingStatus } from "@/app/welcome/types";
import { StepSystemCheck } from "@/app/welcome/_components/StepSystemCheck";
import { StepWorkspaceSetup } from "@/app/welcome/_components/StepWorkspaceSetup";
import { StepAiKeysBudget } from "@/app/welcome/_components/StepAiKeysBudget";
import { StepVoiceFinish } from "@/app/welcome/_components/StepVoiceFinish";
import { PageHeader, PipelineStepItem } from "@/components/vc/PageHeader";
import { Button } from "@/components/ui/button";

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

  const [viProvider, setViProvider] = useState("edge");
  const [viVoice, setViVoice] = useState("vi-VN-HoaiMyNeural-Female");
  const [timezone, setTimezone] = useState("Asia/Ho_Chi_Minh");

  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  const { error: err, setError: setErr } = useApiQuery<OnboardingStatus>(
    (signal) => apiFetch<OnboardingStatus>("/api/v1/onboarding/status", { signal }),
    [],
    {
      fallbackError: "Không tải được trạng thái thiết lập",
      onSuccess: (s) => {
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
      },
    }
  );

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
      state:
        status?.wizard_completed && step === 4
          ? "done"
          : step === 4
            ? "active"
            : "idle",
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
        <StepSystemCheck status={status} onNext={() => setStep(2)} />
      )}

      {step === 2 && (
        <StepWorkspaceSetup
          wsMode={wsMode}
          setWsMode={setWsMode}
          wsName={wsName}
          setWsName={setWsName}
          wsNiche={wsNiche}
          setWsNiche={setWsNiche}
          wsPolicy={wsPolicy}
          setWsPolicy={setWsPolicy}
          wsRatio={wsRatio}
          setWsRatio={setWsRatio}
          wsApproval={wsApproval}
          setWsApproval={setWsApproval}
          onBack={() => setStep(1)}
          onNext={() => setStep(3)}
        />
      )}

      {step === 3 && (
        <StepAiKeysBudget
          configuredSecrets={status?.configured_secrets || []}
          dailyUsd={dailyUsd}
          setDailyUsd={setDailyUsd}
          apiFallback={apiFallback}
          setApiFallback={setApiFallback}
          geminiKey={geminiKey}
          setGeminiKey={setGeminiKey}
          anthropicKey={anthropicKey}
          setAnthropicKey={setAnthropicKey}
          apifyToken={apifyToken}
          setApifyToken={setApifyToken}
          onBack={() => setStep(2)}
          onNext={() => setStep(4)}
        />
      )}

      {step === 4 && (
        <StepVoiceFinish
          viProvider={viProvider}
          setViProvider={setViProvider}
          viVoice={viVoice}
          setViVoice={setViVoice}
          timezone={timezone}
          setTimezone={setTimezone}
          saving={saving}
          onBack={() => setStep(3)}
          onFinish={finishWizard}
        />
      )}
    </div>
  );
}
