"use client";

import React, { useState } from "react";
import { Archive, Cpu, KeyRound, Palette, Settings, Sparkles } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import { PageHeader } from "@/components/vc/PageHeader";
import { Badge } from "@/components/ui/badge";
import { TabPanel, TabsBar, TabsRoot, TabTrigger } from "@/components/ui/overlays";
import {
  BackupSummary,
  LocalModelRow,
  PooledKeyRow,
  SecretMeta,
  VoiceOption,
} from "@/app/settings/types";
import { AppearanceAndWorkerTab } from "@/app/settings/AppearanceAndWorkerTab";
import { AiKeysPoolTab } from "@/app/settings/AiKeysPoolTab";
import { LocalModelsManagerTab } from "@/app/settings/LocalModelsManagerTab";
import { BackupRestoreTab } from "@/app/settings/BackupRestoreTab";
import {
  MuseGatewaySettingsShape,
  MuseGatewayTab,
} from "@/app/settings/MuseGatewayTab";

export default function SettingsPage() {
  const [ioConc, setIoConc] = useState(4);
  const [computeConc, setComputeConc] = useState(1);
  const [dailyUsd, setDailyUsd] = useState(5.0);
  const [apiFallback, setApiFallback] = useState("ask");
  const [timezone, setTimezone] = useState("Asia/Ho_Chi_Minh");
  const [mirrorBaseUrl, setMirrorBaseUrl] = useState("");

  const [viProvider, setViProvider] = useState("edge");
  const [viVoice, setViVoice] = useState("vi-VN-HoaiMyNeural-Female");
  const [catalog, setCatalog] = useState<VoiceOption[]>([]);

  const [secrets, setSecrets] = useState<SecretMeta[]>([]);
  const [localModels, setLocalModels] = useState<LocalModelRow[]>([]);
  const [poolKeys, setPoolKeys] = useState<PooledKeyRow[]>([]);
  const [spentToday, setSpentToday] = useState(0);
  const [backupSummary, setBackupSummary] = useState<BackupSummary | null>(null);
  const [museCfg, setMuseCfg] = useState<MuseGatewaySettingsShape>({
    enabled: false,
    mode: "local_sidecar",
    base_url: "http://127.0.0.1:1412",
    max_parallel: 8,
    renders_per_account: 2,
    daily_cap_video_per_account: 20,
    remote_hardened_confirmed: false,
    include_in_vcx_backup: false,
  });

  const [msg, setMsg] = useState("");

  const { error: err, setError: setErr, reload: load } = useApiQuery(
    async (signal) => {
      const [cfgRes, vRes, secRes, usageRes, modRes, kpRes, bkRes] =
        await Promise.all([
          apiFetch<{
            settings: {
              worker: { io_concurrency: number; compute_concurrency: number };
              budget: { daily_usd: number };
              ai: { policy: { api_fallback: string } };
              schedule: { timezone: string };
              models?: { mirror_base_url?: string };
              muse_gateway?: MuseGatewaySettingsShape;
            };
          }>("/api/v1/settings", { signal }),
          apiFetch<{
            catalog: VoiceOption[];
            voice: { vi_provider: string; vi_voice: string };
          }>("/api/v1/voices", { signal }),
          apiFetch<{ secrets: SecretMeta[] }>("/api/v1/secrets", { signal }),
          apiFetch<{ spent_today_usd: number }>("/api/v1/ai/usage", { signal }),
          apiFetch<{ models: LocalModelRow[] }>("/api/v1/models", { signal }),
          apiFetch<{ keys: PooledKeyRow[] }>("/api/v1/key-pool", { signal }),
          apiFetch<BackupSummary>("/api/v1/backup/summary", { signal }),
        ]);
      return { cfgRes, vRes, secRes, usageRes, modRes, kpRes, bkRes };
    },
    [],
    {
      fallbackError: "Không thể tải cài đặt hệ thống",
      onSuccess: ({ cfgRes, vRes, secRes, usageRes, modRes, kpRes, bkRes }) => {
        const s = cfgRes.settings;
        setIoConc(s.worker?.io_concurrency ?? 4);
        setComputeConc(s.worker?.compute_concurrency ?? 1);
        setDailyUsd(s.budget?.daily_usd ?? 5.0);
        setApiFallback(s.ai?.policy?.api_fallback ?? "ask");
        setTimezone(s.schedule?.timezone ?? "Asia/Ho_Chi_Minh");
        setMirrorBaseUrl(s.models?.mirror_base_url ?? "");

        setCatalog(vRes.catalog || []);
        setViProvider(vRes.voice?.vi_provider || "edge");
        setViVoice(vRes.voice?.vi_voice || "vi-VN-HoaiMyNeural-Female");
        setSecrets(secRes.secrets || []);
        setSpentToday(usageRes.spent_today_usd || 0);
        setLocalModels(modRes.models || []);
        setPoolKeys(kpRes.keys || []);
        setBackupSummary(bkRes);
        if (s.muse_gateway) {
          setMuseCfg((prev) => ({ ...prev, ...s.muse_gateway }));
        }
      },
    }
  );

  const readyModels = localModels.filter((m) => m.status === "ready").length;

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <PageHeader
        icon={<Settings className="w-5 h-5" />}
        title="Cài đặt Giao diện, Mô hình AI & Bảo mật"
        badges={
          <>
            <Badge tone="cluster" className="tabular-nums">
              Chi tiêu hôm nay: ${spentToday.toFixed(3)} / ${dailyUsd.toFixed(2)}
            </Badge>
            <Badge tone="emerald" className="tabular-nums">
              {readyModels}/{localModels.length} mô hình sẵn sàng
            </Badge>
          </>
        }
        description="Tùy chỉnh chế độ Sáng/Tối, luồng xử lý nền, kho khóa API mã hóa DPAPI cục bộ, mô hình AI chạy trên CPU và sao lưu định dạng .vcx."
      />

      {msg && (
        <div
          role="status"
          className="rounded-[11px] border border-[var(--st-emerald-bd)] bg-[var(--st-emerald-bg)] px-4 py-2.5 text-[13px] text-[var(--st-emerald-tx)]"
        >
          {msg}
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

      <TabsRoot defaultValue="appearance" className="space-y-4">
        <TabsBar aria-label="Các phân mục cài đặt">
          <TabTrigger value="appearance">
            <Palette className="w-4 h-4" /> Giao diện &amp; Hệ thống
          </TabTrigger>
          <TabTrigger value="keys">
            <KeyRound className="w-4 h-4" /> Kho Khóa API ({poolKeys.length})
          </TabTrigger>
          <TabTrigger value="models">
            <Cpu className="w-4 h-4" /> Mô hình AI CPU ({readyModels}/
            {localModels.length})
          </TabTrigger>
          <TabTrigger value="muse">
            <Sparkles className="w-4 h-4" /> Muse Gateway
          </TabTrigger>
          <TabTrigger value="backup">
            <Archive className="w-4 h-4" /> Sao lưu &amp; Khôi phục (.vcx)
          </TabTrigger>
        </TabsBar>

        <TabPanel value="appearance">
          <AppearanceAndWorkerTab
            ioConc={ioConc}
            setIoConc={setIoConc}
            computeConc={computeConc}
            setComputeConc={setComputeConc}
            dailyUsd={dailyUsd}
            setDailyUsd={setDailyUsd}
            apiFallback={apiFallback}
            setApiFallback={setApiFallback}
            timezone={timezone}
            setTimezone={setTimezone}
            mirrorBaseUrl={mirrorBaseUrl}
            viProvider={viProvider}
            setViProvider={setViProvider}
            viVoice={viVoice}
            setViVoice={setViVoice}
            catalog={catalog}
            onReload={load}
            onMessage={setMsg}
            onError={setErr}
          />
        </TabPanel>

        <TabPanel value="keys">
          <AiKeysPoolTab
            secrets={secrets}
            poolKeys={poolKeys}
            onReload={load}
            onMessage={setMsg}
          />
        </TabPanel>

        <TabPanel value="models">
          <LocalModelsManagerTab
            localModels={localModels}
            mirrorBaseUrl={mirrorBaseUrl}
            setMirrorBaseUrl={setMirrorBaseUrl}
            onReload={load}
            onMessage={setMsg}
            onError={setErr}
          />
        </TabPanel>

        <TabPanel value="muse">
          <MuseGatewayTab
            initialConfig={museCfg}
            onReloadParent={load}
            onMessage={setMsg}
            onError={setErr}
          />
        </TabPanel>

        <TabPanel value="backup">
          <BackupRestoreTab
            backupSummary={backupSummary}
            onReload={load}
            onMessage={setMsg}
            onError={setErr}
          />
        </TabPanel>
      </TabsRoot>
    </div>
  );
}
