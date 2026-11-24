"use client";

import React, { useCallback, useEffect, useState } from "react";
import { KeyRound, Save, Settings } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface SecretMeta {
  name: string;
  label: string;
  configured: boolean;
}

interface VoiceOption {
  provider: string;
  lang: string;
  voice: string;
  label: string;
}

export default function SettingsPage() {
  const [ioConc, setIoConc] = useState(4);
  const [computeConc, setComputeConc] = useState(1);
  const [dailyUsd, setDailyUsd] = useState(5.0);
  const [apiFallback, setApiFallback] = useState("ask");
  const [timezone, setTimezone] = useState("Asia/Ho_Chi_Minh");

  const [viProvider, setViProvider] = useState("edge");
  const [viVoice, setViVoice] = useState("vi-VN-HoaiMyNeural-Female");
  const [catalog, setCatalog] = useState<VoiceOption[]>([]);

  const [secrets, setSecrets] = useState<SecretMeta[]>([]);
  const [secretInputs, setSecretInputs] = useState<Record<string, string>>({});
  const [spentToday, setSpentToday] = useState(0);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [cfgRes, vRes, secRes, usageRes] = await Promise.all([
        apiFetch<{
          settings: {
            worker: { io_concurrency: number; compute_concurrency: number };
            budget: { daily_usd: number };
            ai: { policy: { api_fallback: string } };
            schedule: { timezone: string };
          };
        }>("/api/v1/settings"),
        apiFetch<{
          catalog: VoiceOption[];
          voice: { vi_provider: string; vi_voice: string };
        }>("/api/v1/voices"),
        apiFetch<{ secrets: SecretMeta[] }>("/api/v1/secrets"),
        apiFetch<{ spent_today_usd: number }>("/api/v1/ai/usage"),
      ]);
      const s = cfgRes.settings;
      setIoConc(s.worker?.io_concurrency ?? 4);
      setComputeConc(s.worker?.compute_concurrency ?? 1);
      setDailyUsd(s.budget?.daily_usd ?? 5.0);
      setApiFallback(s.ai?.policy?.api_fallback ?? "ask");
      setTimezone(s.schedule?.timezone ?? "Asia/Ho_Chi_Minh");

      setCatalog(vRes.catalog || []);
      setViProvider(vRes.voice?.vi_provider || "edge");
      setViVoice(vRes.voice?.vi_voice || "vi-VN-HoaiMyNeural-Female");
      setSecrets(secRes.secrets || []);
      setSpentToday(usageRes.spent_today_usd || 0);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải cài đặt");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const saveConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      await Promise.all([
        apiFetch("/api/v1/settings", {
          method: "PUT",
          body: JSON.stringify({
            worker: { io_concurrency: ioConc, compute_concurrency: computeConc },
            budget: { daily_usd: dailyUsd },
            ai: { policy: { api_fallback: apiFallback } },
            schedule: { timezone },
          }),
        }),
        apiFetch("/api/v1/voices", {
          method: "PUT",
          body: JSON.stringify({ vi_provider: viProvider, vi_voice: viVoice }),
        }),
      ]);
      setMsg("Đã lưu cấu hình Worker, Ngân sách AI & Giọng đọc.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi lưu cấu hình");
    }
  };

  const saveSecrets = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    const nonEmpty: Record<string, string> = {};
    for (const [k, v] of Object.entries(secretInputs)) {
      if (v.trim()) nonEmpty[k] = v.trim();
    }
    await apiFetch("/api/v1/secrets", {
      method: "PUT",
      body: JSON.stringify({ secrets: nonEmpty }),
    });
    setSecretInputs({});
    setMsg("Đã mã hóa và lưu các API Keys.");
    await load();
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Settings className="w-6 h-6 text-sky-400" /> Cài đặt Hệ thống & Bảo mật API Keys
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Chi tiêu AI hôm nay: <strong className="text-white">${spentToday.toFixed(3)}</strong> /
          ${dailyUsd.toFixed(2)} • Toàn bộ API Keys được mã hóa cục bộ, không bao giờ lộ ra JSON.
        </p>
      </div>

      {msg && (
        <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs rounded-lg px-4 py-2.5">
          {msg}
        </div>
      )}
      {err && (
        <div className="bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs rounded-lg px-4 py-2.5">
          {err}
        </div>
      )}

      <form
        onSubmit={saveConfig}
        className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-4 text-xs"
      >
        <h2 className="text-sm font-semibold text-white">Hàng đợi 2 làn, Ngân sách & Giọng đọc</h2>
        <div className="grid md:grid-cols-3 gap-3">
          <div>
            <label className="text-slate-400 block mb-1">Số luồng Làn IO</label>
            <input
              type="number"
              min={1}
              max={16}
              value={ioConc}
              onChange={(e) => setIoConc(Number(e.target.value))}
              className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            />
          </div>
          <div>
            <label className="text-slate-400 block mb-1">Số luồng Làn Compute</label>
            <input
              type="number"
              min={1}
              max={4}
              value={computeConc}
              onChange={(e) => setComputeConc(Number(e.target.value))}
              className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            />
          </div>
          <div>
            <label className="text-slate-400 block mb-1">Trần chi phí AI / ngày (USD)</label>
            <input
              type="number"
              step="0.5"
              min={0}
              value={dailyUsd}
              onChange={(e) => setDailyUsd(Number(e.target.value))}
              className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            />
          </div>
        </div>

        <div className="grid md:grid-cols-3 gap-3">
          <div>
            <label className="text-slate-400 block mb-1">Subscription-First Fallback</label>
            <select
              value={apiFallback}
              onChange={(e) => setApiFallback(e.target.value)}
              className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            >
              <option value="ask">Ask (Hỏi khi hết quota gói thuê bao)</option>
              <option value="never">Never (Chỉ dùng thuê bao)</option>
              <option value="auto">Auto (Tự chuyển sang API)</option>
            </select>
          </div>
          <div>
            <label className="text-slate-400 block mb-1">Múi giờ lịch đăng</label>
            <input
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            />
          </div>
          <div>
            <label className="text-slate-400 block mb-1">Giọng đọc Tiếng Việt mặc định</label>
            <select
              value={`${viProvider}:${viVoice}`}
              onChange={(e) => {
                const [p, v] = e.target.value.split(":");
                setViProvider(p);
                setViVoice(v);
              }}
              className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
            >
              {catalog
                .filter((c) => c.lang === "vi")
                .map((c) => (
                  <option key={`${c.provider}:${c.voice}`} value={`${c.provider}:${c.voice}`}>
                    {c.label}
                  </option>
                ))}
            </select>
          </div>
        </div>

        <button
          type="submit"
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold cursor-pointer"
        >
          <Save className="w-4 h-4" /> Lưu Cài Đặt
        </button>
      </form>

      <form
        onSubmit={saveSecrets}
        className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs"
      >
        <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
          <KeyRound className="w-4 h-4 text-amber-400" /> Kho API Keys (Mã hóa DPAPI / Fernet)
        </h2>
        <div className="grid md:grid-cols-2 gap-3">
          {secrets.map((item) => (
            <div key={item.name} className="space-y-1">
              <div className="flex justify-between text-[11px]">
                <label className="text-slate-300 font-medium">{item.name}</label>
                <span className={item.configured ? "text-emerald-400" : "text-slate-500"}>
                  {item.configured ? "✓ Đã cấu hình" : "Chưa đặt"}
                </span>
              </div>
              <input
                type="password"
                placeholder={item.label}
                value={secretInputs[item.name] || ""}
                onChange={(e) =>
                  setSecretInputs((prev) => ({ ...prev, [item.name]: e.target.value }))
                }
                className="w-full bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
              />
            </div>
          ))}
        </div>
        <button
          type="submit"
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-amber-300 border border-slate-700 font-semibold cursor-pointer"
        >
          <Save className="w-4 h-4" /> Lưu API Keys Mới
        </button>
      </form>
    </div>
  );
}
