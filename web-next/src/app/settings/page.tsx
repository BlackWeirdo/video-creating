"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Archive, Cpu, Download, KeyRound, Plus, Rocket, Save, Settings, Trash2, Upload } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface LocalModelRow {
  model_id: string;
  name: string;
  category: string;
  size_mb: number;
  status: string;
  progress: number;
  installed_on_disk: boolean;
}

interface PooledKeyRow {
  id: number;
  provider: string;
  label: string;
  masked_preview: string;
  enabled: boolean;
  priority: number;
  is_cooling_down: boolean;
  use_count: number;
}

interface BackupSummary {
  db_size_bytes: number;
  workspaces: number;
  products: number;
  workflows: number;
  channels: number;
  pooled_keys: number;
  secrets_count: number;
  snapshots: Array<{ filename: string; size_bytes: number }>;
}

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
  const [localModels, setLocalModels] = useState<LocalModelRow[]>([]);
  const [poolKeys, setPoolKeys] = useState<PooledKeyRow[]>([]);
  const [poolProvider, setPoolProvider] = useState("gemini");
  const [poolLabel, setPoolLabel] = useState("");
  const [poolSecret, setPoolSecret] = useState("");
  const [spentToday, setSpentToday] = useState(0);
  const [backupSummary, setBackupSummary] = useState<BackupSummary | null>(null);
  const [backupPassword, setBackupPassword] = useState("");
  const [restorePassword, setRestorePassword] = useState("");
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [cfgRes, vRes, secRes, usageRes, modRes, kpRes, bkRes] = await Promise.all([
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
        apiFetch<{ models: LocalModelRow[] }>("/api/v1/models"),
        apiFetch<{ keys: PooledKeyRow[] }>("/api/v1/key-pool"),
        apiFetch<BackupSummary>("/api/v1/backup/summary"),
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
      setLocalModels(modRes.models || []);
      setPoolKeys(kpRes.keys || []);
      setBackupSummary(bkRes);
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

      {/* Multi-Key Rotation Pool */}
      <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs">
        <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
          <KeyRound className="w-4 h-4 text-emerald-400" /> Bể Xoay Vòng Nhiều API Key ({poolKeys.length})
        </h2>
        <div className="grid md:grid-cols-4 gap-2">
          <select
            value={poolProvider}
            onChange={(e) => setPoolProvider(e.target.value)}
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="gemini">Gemini</option>
            <option value="claude">Claude</option>
            <option value="openai_compat">OpenAI-compat</option>
            <option value="fal">fal.ai</option>
            <option value="elevenlabs">ElevenLabs</option>
            <option value="muse">Muse Spark</option>
          </select>
          <input
            value={poolLabel}
            onChange={(e) => setPoolLabel(e.target.value)}
            placeholder="Nhãn (VD: Tài khoản 1)"
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <input
            type="password"
            value={poolSecret}
            onChange={(e) => setPoolSecret(e.target.value)}
            placeholder="Dán API Key mới vào pool..."
            className="bg-[#182235] border border-slate-700 rounded-lg px-3 py-2"
          />
          <button
            type="button"
            onClick={async () => {
              if (!poolSecret.trim()) return;
              await apiFetch("/api/v1/key-pool", {
                method: "POST",
                body: JSON.stringify({
                  provider: poolProvider,
                  label: poolLabel,
                  raw_secret: poolSecret,
                }),
              });
              setPoolLabel("");
              setPoolSecret("");
              setMsg("Đã thêm API Key vào bể xoay vòng.");
              await load();
            }}
            className="inline-flex items-center justify-center gap-1 px-3 py-2 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 font-semibold cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5" /> Thêm vào Pool
          </button>
        </div>
        <div className="space-y-1.5">
          {poolKeys.map((k) => (
            <div
              key={k.id}
              className="flex items-center justify-between bg-[#182235] border border-slate-800 rounded-lg px-3 py-2"
            >
              <div>
                <span className="uppercase text-sky-300 font-semibold mr-2">{k.provider}</span>
                <span className="text-white">{k.label || `Key #${k.id}`}</span>{" "}
                <span className="text-slate-400">({k.masked_preview})</span>
                <span className="ml-2 text-[11px] text-slate-400">
                  Dùng: {k.use_count} {k.is_cooling_down ? "• Đang cooldown" : ""}
                </span>
              </div>
              <button
                type="button"
                onClick={async () => {
                  await apiFetch(`/api/v1/key-pool/${k.id}`, { method: "DELETE" });
                  await load();
                }}
                className="text-slate-400 hover:text-rose-400 cursor-pointer"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* On-Demand Local AI Models Manager */}
      <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-3 text-xs">
        <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
          <Cpu className="w-4 h-4 text-purple-400" /> Kho Model AI Cục Bộ (Tải theo nhu cầu)
        </h2>
        <div className="grid md:grid-cols-2 gap-3">
          {localModels.map((m) => (
            <div
              key={m.model_id}
              className="bg-[#182235] border border-slate-800 rounded-lg p-3 flex items-center justify-between gap-2"
            >
              <div>
                <div className="font-semibold text-white">{m.name}</div>
                <div className="text-[11px] text-slate-400">
                  {m.category} • ~{m.size_mb} MB • Trạng thái:{" "}
                  <span className={m.status === "ready" ? "text-emerald-300" : "text-amber-300"}>
                    {m.status}
                  </span>
                </div>
              </div>
              <div className="flex gap-1.5 shrink-0">
                {m.status !== "ready" ? (
                  <button
                    type="button"
                    onClick={async () => {
                      await apiFetch(`/api/v1/models/${m.model_id}/install`, {
                        method: "POST",
                        body: JSON.stringify({}),
                      });
                      setMsg(`Đã xếp hàng tải model ${m.model_id}.`);
                      await load();
                    }}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-sky-500/20 text-sky-300 cursor-pointer"
                  >
                    <Download className="w-3 h-3" /> Tải về
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={async () => {
                      await apiFetch(`/api/v1/models/${m.model_id}`, { method: "DELETE" });
                      await load();
                    }}
                    className="px-2.5 py-1 rounded bg-rose-500/15 text-rose-300 cursor-pointer"
                  >
                    Gỡ
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Encrypted Backup / Restore (.vcx) + Welcome Wizard */}
      <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 space-y-4 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
            <Archive className="w-4 h-4 text-sky-400" /> Sao lưu &amp; Khôi phục Cấu hình Mã hóa (`.vcx`)
          </h2>
          <Link
            href="/welcome"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-500/20 hover:bg-sky-500/30 text-sky-300 font-semibold"
          >
            <Rocket className="w-3.5 h-3.5" /> Mở Welcome Wizard
          </Link>
        </div>

        {backupSummary && (
          <div className="text-[11px] text-slate-400">
            Cơ sở dữ liệu: {(backupSummary.db_size_bytes / 1024).toFixed(1)} KB •{" "}
            {backupSummary.workspaces} workspaces • {backupSummary.products} sản phẩm •{" "}
            {backupSummary.workflows} workflows • {backupSummary.secrets_count} khóa bảo mật
          </div>
        )}

        <div className="grid md:grid-cols-2 gap-4">
          <div className="bg-[#182235] border border-slate-800 rounded-lg p-3.5 space-y-2">
            <div className="font-semibold text-white">Xuất gói Sao lưu Mã hóa (.vcx)</div>
            <input
              type="password"
              value={backupPassword}
              onChange={(e) => setBackupPassword(e.target.value)}
              placeholder="Mật khẩu mã hóa (ít nhất 4 ký tự)"
              className="w-full bg-[#111827] border border-slate-700 rounded px-3 py-1.5"
            />
            <button
              type="button"
              onClick={async () => {
                setErr("");
                setMsg("");
                const resp = await fetch("/api/v1/backup/export", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ password: backupPassword, save_copy: true }),
                });
                if (!resp.ok) {
                  setErr("Xuất sao lưu thất bại (kiểm tra mật khẩu >= 4 ký tự).");
                  return;
                }
                const blob = await resp.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "videocreator-v2-backup.vcx";
                a.click();
                URL.revokeObjectURL(url);
                setBackupPassword("");
                setMsg("Đã xuất gói sao lưu .vcx mã hóa và lưu bản cục bộ.");
                await load();
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-sky-500 text-slate-950 font-semibold cursor-pointer"
            >
              <Download className="w-3.5 h-3.5" /> Tải file .vcx
            </button>
          </div>

          <div className="bg-[#182235] border border-slate-800 rounded-lg p-3.5 space-y-2">
            <div className="font-semibold text-white">Khôi phục từ file .vcx</div>
            <input
              type="file"
              accept=".vcx"
              onChange={(e) => setRestoreFile(e.target.files?.[0] || null)}
              className="w-full text-[11px] text-slate-300"
            />
            <input
              type="password"
              value={restorePassword}
              onChange={(e) => setRestorePassword(e.target.value)}
              placeholder="Mật khẩu giải mã file .vcx"
              className="w-full bg-[#111827] border border-slate-700 rounded px-3 py-1.5"
            />
            <button
              type="button"
              onClick={async () => {
                if (!restoreFile) return;
                setErr("");
                setMsg("");
                try {
                  const fd = new FormData();
                  fd.append("file", restoreFile);
                  fd.append("password", restorePassword);
                  fd.append("as_server", "true");
                  await apiFetch("/api/v1/backup/restore", { method: "POST", body: fd });
                  setRestorePassword("");
                  setRestoreFile(null);
                  setMsg("Đã khôi phục toàn bộ Workspaces, DB và API Keys từ gói .vcx!");
                  await load();
                } catch (e2) {
                  setErr(e2 instanceof Error ? e2.message : "Khôi phục .vcx thất bại");
                }
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-emerald-500 text-slate-950 font-semibold cursor-pointer"
            >
              <Upload className="w-3.5 h-3.5" /> Khôi phục .vcx
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
