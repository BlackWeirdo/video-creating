"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Cpu, KeyRound, Layers, Rocket, RotateCcw, Sparkles, Volume2 } from "lucide-react";
import { apiFetch, useWorkspace, Workspace } from "@/lib/api";

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

  // Step 2: Workspace setup
  const [wsMode, setWsMode] = useState<"update" | "create">("update");
  const [wsName, setWsName] = useState("");
  const [wsNiche, setWsNiche] = useState("general");
  const [wsPolicy, setWsPolicy] = useState<Workspace["content_policy"]>("strict_footage");
  const [wsApproval, setWsApproval] = useState<Workspace["approval_mode"]>("single");
  const [wsRatio, setWsRatio] = useState<Workspace["default_aspect_ratio"]>("9:16");

  // Step 3: AI & Budget
  const [dailyUsd, setDailyUsd] = useState(5.0);
  const [apiFallback, setApiFallback] = useState("ask");
  const [geminiKey, setGeminiKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [apifyToken, setApifyToken] = useState("");

  // Step 4: Voice & Timezone
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
      setErr(e instanceof Error ? e.message : "Không tải được trạng thái Onboarding");
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

      const res = await apiFetch<OnboardingStatus>("/api/v1/onboarding/complete", {
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
      });
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
      setMsg("Hoàn tất thiết lập ban đầu! Bạn có thể bắt đầu sản xuất video ngay.");
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi hoàn tất Welcome Wizard");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Sparkles className="w-6 h-6 text-sky-400" /> Welcome Wizard — Video Creator V2
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Thiết lập nhanh môi trường máy trạm độc lập, Workspace đầu tiên, AI Keys &amp; Giọng đọc mặc định.
          </p>
        </div>
        {status?.wizard_completed && (
          <button
            type="button"
            onClick={async () => {
              const s = await apiFetch<OnboardingStatus>("/api/v1/onboarding/reset", {
                method: "POST",
              });
              setStatus(s);
              if (typeof window !== "undefined") {
                window.dispatchEvent(new Event("vc:onboarding-updated"));
              }
              setStep(1);
            }}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs cursor-pointer"
          >
            <RotateCcw className="w-3.5 h-3.5" /> Chạy lại từ bước 1
          </button>
        )}
      </div>

      {/* Stepper Header */}
      <div className="grid grid-cols-4 gap-2 text-xs">
        {[
          { id: 1, title: "1. Kiểm tra Máy", icon: Cpu },
          { id: 2, title: "2. Workspace", icon: Layers },
          { id: 3, title: "3. AI Keys & Quỹ", icon: KeyRound },
          { id: 4, title: "4. Giọng & Xong", icon: Volume2 },
        ].map((item) => {
          const Icon = item.icon;
          const active = step === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setStep(item.id)}
              className={`flex items-center gap-2 px-3 py-2.5 rounded-lg border text-left cursor-pointer ${
                active
                  ? "bg-sky-500/20 border-sky-400/50 text-sky-200 font-semibold"
                  : "bg-[#111827] border-slate-800 text-slate-400 hover:text-slate-200"
              }`}
            >
              <Icon className="w-4 h-4 shrink-0" />
              <span>{item.title}</span>
            </button>
          );
        })}
      </div>

      {msg && (
        <div className="bg-emerald-500/15 border border-emerald-500/40 text-emerald-200 text-xs rounded-lg px-4 py-3 flex items-center justify-between gap-3">
          <span className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4" /> {msg}
          </span>
          <Link
            href="/"
            className="px-3 py-1 rounded bg-emerald-500 text-slate-950 font-semibold"
          >
            Vào Tổng quan →
          </Link>
        </div>
      )}
      {err && (
        <div className="bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs rounded-lg px-4 py-2.5">
          {err}
        </div>
      )}

      {/* Step 1: Runtime Health */}
      {step === 1 && status && (
        <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-4 text-xs">
          <h2 className="text-sm font-semibold text-white">Kiểm tra Thành phần Cục bộ trên Máy</h2>
          <div className="grid md:grid-cols-2 gap-3">
            {[
              { name: "FFmpeg Renderer", ok: status.runtime.ffmpeg_ready, note: status.runtime.ffmpeg_path },
              { name: "FFprobe Inspector", ok: status.runtime.ffprobe_ready, note: "Đo thời lượng & codec MP4" },
              { name: "Node 24 LTS UI Runtime", ok: status.runtime.node_ready, note: status.runtime.node_path || "Next.js & Remotion" },
              { name: "yt-dlp Trend Downloader", ok: status.runtime.ytdlp_ready, note: "Tải video tham khảo & nguồn Việt hóa" },
            ].map((chk) => (
              <div
                key={chk.name}
                className="bg-[#182235] border border-slate-800 rounded-lg p-3 flex items-center justify-between gap-2"
              >
                <div className="min-w-0">
                  <div className="font-semibold text-white">{chk.name}</div>
                  <div className="text-[11px] text-slate-400 truncate">{chk.note}</div>
                </div>
                <span
                  className={`px-2 py-0.5 rounded-full text-[11px] font-semibold shrink-0 ${
                    chk.ok
                      ? "bg-emerald-500/20 text-emerald-300"
                      : "bg-amber-500/20 text-amber-300"
                  }`}
                >
                  {chk.ok ? "Sẵn sàng" : "Thiếu"}
                </span>
              </div>
            ))}
          </div>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => setStep(2)}
              className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
            >
              Tiếp tục: Workspace →
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Workspace & Policy */}
      {step === 2 && (
        <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-4 text-xs">
          <h2 className="text-sm font-semibold text-white">Cấu hình Workspace Đầu tiên &amp; Chính sách Nội dung</h2>
          <div className="flex gap-3">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="radio"
                checked={wsMode === "update"}
                onChange={() => setWsMode("update")}
              />
              Cập nhật Workspace hiện tại
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="radio"
                checked={wsMode === "create"}
                onChange={() => {
                  setWsMode("create");
                  setWsName("");
                }}
              />
              Tạo Workspace mới riêng biệt
            </label>
          </div>
          <div className="grid md:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-slate-300">Tên thương hiệu / Dự án</label>
              <input
                value={wsName}
                onChange={(e) => setWsName(e.target.value)}
                placeholder="VD: Trang Sức Bạc S925"
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              />
            </div>
            <div className="space-y-1">
              <label className="text-slate-300">Ngành hàng / Chủ đề</label>
              <input
                value={wsNiche}
                onChange={(e) => setWsNiche(e.target.value)}
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              />
            </div>
            <div className="space-y-1">
              <label className="text-slate-300">Chính sách Nội dung</label>
              <select
                value={wsPolicy}
                onChange={(e) => setWsPolicy(e.target.value as Workspace["content_policy"])}
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              >
                <option value="strict_footage">Strict Footage (100% footage thật - BR-PRD-01)</option>
                <option value="hybrid_remix">Hybrid Remix (Việt hóa + chèn shot thật)</option>
                <option value="full_ai">Full AI (Tiểu thuyết, Tin tức, Podcast, Reup)</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-slate-300">Khung hình &amp; Duyệt bài mặc định</label>
              <div className="grid grid-cols-2 gap-2">
                <select
                  value={wsRatio}
                  onChange={(e) => setWsRatio(e.target.value as Workspace["default_aspect_ratio"])}
                  className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
                >
                  <option value="9:16">9:16 Dọc</option>
                  <option value="16:9">16:9 Ngang</option>
                  <option value="1:1">1:1 Vuông</option>
                </select>
                <select
                  value={wsApproval}
                  onChange={(e) => setWsApproval(e.target.value as Workspace["approval_mode"])}
                  className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
                >
                  <option value="single">Duyệt từng bài</option>
                  <option value="bulk">Duyệt theo lô</option>
                  <option value="autopilot">Autopilot theo QC</option>
                </select>
              </div>
            </div>
          </div>
          <div className="flex justify-between">
            <button
              type="button"
              onClick={() => setStep(1)}
              className="px-3 py-2 rounded-lg bg-slate-800 text-slate-300 cursor-pointer"
            >
              ← Quay lại
            </button>
            <button
              type="button"
              onClick={() => setStep(3)}
              className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
            >
              Tiếp tục: AI Keys →
            </button>
          </div>
        </div>
      )}

      {/* Step 3: AI Keys & Budget */}
      {step === 3 && (
        <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-4 text-xs">
          <h2 className="text-sm font-semibold text-white">Mã hóa API Keys &amp; Ngân sách Ngày</h2>
          <p className="text-slate-400">
            Khóa đã lưu trên máy: {(status?.configured_secrets || []).join(", ") || "Chưa có (có thể bỏ qua và dùng chế độ offline/subscription)."}
          </p>
          <div className="grid md:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-slate-300">Trần chi phí API / ngày (USD)</label>
              <input
                type="number"
                step="0.5"
                value={dailyUsd}
                onChange={(e) => setDailyUsd(Number(e.target.value))}
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              />
            </div>
            <div className="space-y-1">
              <label className="text-slate-300">Chính sách vượt gói thuê bao</label>
              <select
                value={apiFallback}
                onChange={(e) => setApiFallback(e.target.value)}
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              >
                <option value="ask">Hỏi trước khi dùng API trả phí (ask)</option>
                <option value="auto">Tự chuyển API khi hết quota gói (auto)</option>
                <option value="never">Không bao giờ gọi API ngoài gói (never)</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-slate-300">Gemini API Key (tùy chọn)</label>
              <input
                type="password"
                value={geminiKey}
                onChange={(e) => setGeminiKey(e.target.value)}
                placeholder="AIza..."
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              />
            </div>
            <div className="space-y-1">
              <label className="text-slate-300">Anthropic Claude Key (tùy chọn)</label>
              <input
                type="password"
                value={anthropicKey}
                onChange={(e) => setAnthropicKey(e.target.value)}
                placeholder="sk-ant-..."
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              />
            </div>
            <div className="space-y-1 md:col-span-2">
              <label className="text-slate-300">Apify Token (quét Trend Facebook/TikTok/IG, tùy chọn)</label>
              <input
                type="password"
                value={apifyToken}
                onChange={(e) => setApifyToken(e.target.value)}
                placeholder="apify_api_..."
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              />
            </div>
          </div>
          <div className="flex justify-between">
            <button
              type="button"
              onClick={() => setStep(2)}
              className="px-3 py-2 rounded-lg bg-slate-800 text-slate-300 cursor-pointer"
            >
              ← Quay lại
            </button>
            <button
              type="button"
              onClick={() => setStep(4)}
              className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
            >
              Tiếp tục: Giọng đọc →
            </button>
          </div>
        </div>
      )}

      {/* Step 4: Voice & Finish */}
      {step === 4 && (
        <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-4 text-xs">
          <h2 className="text-sm font-semibold text-white">Giọng đọc Tiếng Việt Mặc định &amp; Múi giờ</h2>
          <div className="grid md:grid-cols-3 gap-3">
            <div className="space-y-1">
              <label className="text-slate-300">TTS Provider</label>
              <select
                value={viProvider}
                onChange={(e) => setViProvider(e.target.value)}
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              >
                <option value="edge">Edge TTS (trực tuyến miễn phí — mặc định)</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-slate-300">Giọng Tiếng Việt</label>
              <select
                value={viVoice}
                onChange={(e) => setViVoice(e.target.value)}
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              >
                <option value="vi-VN-HoaiMyNeural-Female">Hoài My (Nữ miền Bắc)</option>
                <option value="vi-VN-NamMinhNeural-Male">Nam Minh (Nam)</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-slate-300">Múi giờ Lịch đăng</label>
              <input
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              />
            </div>
          </div>
          <div className="flex justify-between">
            <button
              type="button"
              onClick={() => setStep(3)}
              className="px-3 py-2 rounded-lg bg-slate-800 text-slate-300 cursor-pointer"
            >
              ← Quay lại
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={() => void finishWizard()}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold cursor-pointer disabled:opacity-50"
            >
              <Rocket className="w-4 h-4" />{" "}
              {saving ? "Đang lưu cấu hình..." : "Hoàn tất Welcome Wizard"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
