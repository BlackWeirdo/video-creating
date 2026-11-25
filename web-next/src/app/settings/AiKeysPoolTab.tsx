"use client";

import React, { useState } from "react";
import { Eye, EyeOff, KeyRound, Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { PooledKeyRow, SecretMeta } from "@/app/settings/types";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextInput } from "@/components/ui/form-controls";
import { EmptyState } from "@/components/vc/StatCard";

export function AiKeysPoolTab({
  secrets,
  poolKeys,
  onReload,
  onMessage,
}: {
  secrets: SecretMeta[];
  poolKeys: PooledKeyRow[];
  onReload: () => Promise<void>;
  onMessage: (m: string) => void;
}) {
  const [secretInputs, setSecretInputs] = useState<Record<string, string>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [poolProvider, setPoolProvider] = useState("gemini");
  const [poolLabel, setPoolLabel] = useState("");
  const [poolSecret, setPoolSecret] = useState("");
  const [showPoolSecret, setShowPoolSecret] = useState(false);

  const saveSecrets = async (e: React.FormEvent) => {
    e.preventDefault();
    const nonEmpty: Record<string, string> = {};
    for (const [k, v] of Object.entries(secretInputs)) {
      if (v.trim()) nonEmpty[k] = v.trim();
    }
    await apiFetch("/api/v1/secrets", {
      method: "PUT",
      body: JSON.stringify({ secrets: nonEmpty }),
    });
    setSecretInputs({});
    const m = "Đã mã hóa và lưu các khóa API cục bộ.";
    onMessage(m);
    toast.success(m);
    await onReload();
  };

  const addPoolKey = async () => {
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
    const m = "Đã thêm khóa mới vào bể xoay vòng tự động.";
    onMessage(m);
    toast.success(m);
    await onReload();
  };

  return (
    <div className="space-y-4">
      <Card tinted>
        <form onSubmit={saveSecrets} className="space-y-4">
          <SectionHeading>
            <KeyRound className="w-4 h-4 text-[var(--c-icon)]" /> Kho Khóa API Bảo Mật (Mã hóa Windows DPAPI)
          </SectionHeading>

          <div className="grid md:grid-cols-2 gap-3.5">
            {secrets.map((item) => {
              const isVis = Boolean(revealed[item.name]);
              return (
                <div key={item.name}>
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <FieldLabel htmlFor={`sec-${item.name}`} className="mb-0">
                      {item.name}
                    </FieldLabel>
                    <Badge tone={item.configured ? "emerald" : "neutral"}>
                      {item.configured ? "✓ Đã cấu hình" : "Chưa đặt"}
                    </Badge>
                  </div>
                  <div className="relative">
                    <TextInput
                      id={`sec-${item.name}`}
                      type={isVis ? "text" : "password"}
                      placeholder={item.label}
                      value={secretInputs[item.name] || ""}
                      onChange={(e) =>
                        setSecretInputs((prev) => ({
                          ...prev,
                          [item.name]: e.target.value,
                        }))
                      }
                      className="pr-10"
                    />
                    <button
                      type="button"
                      onClick={() =>
                        setRevealed((prev) => ({
                          ...prev,
                          [item.name]: !prev[item.name],
                        }))
                      }
                      aria-label={isVis ? `Ẩn ${item.name}` : `Hiện ${item.name}`}
                      className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
                    >
                      {isVis ? (
                        <EyeOff className="w-4 h-4" />
                      ) : (
                        <Eye className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          <Button type="submit">
            <Save className="w-4 h-4" /> Lưu Khóa API Mới
          </Button>
        </form>
      </Card>

      <Card className="space-y-3.5">
        <SectionHeading className="tabular-nums">
          <KeyRound className="w-4 h-4 text-[var(--c-icon)]" /> Bể Xoay Vòng Nhiều Khóa API ({poolKeys.length})
        </SectionHeading>

        <div className="grid md:grid-cols-4 gap-2.5 items-end">
          <div>
            <FieldLabel htmlFor="pool-prov">Nhà cung cấp</FieldLabel>
            <SelectBox
              id="pool-prov"
              value={poolProvider}
              onChange={(e) => setPoolProvider(e.target.value)}
            >
              <option value="gemini">Gemini</option>
              <option value="claude">Claude</option>
              <option value="openai_compat">OpenAI tương thích</option>
              <option value="fal">fal.ai</option>
              <option value="elevenlabs">ElevenLabs</option>
              <option value="muse">Muse Spark</option>
            </SelectBox>
          </div>
          <div>
            <FieldLabel htmlFor="pool-lbl">Nhãn gợi nhớ</FieldLabel>
            <TextInput
              id="pool-lbl"
              value={poolLabel}
              onChange={(e) => setPoolLabel(e.target.value)}
              placeholder="VD: Tài khoản 1"
            />
          </div>
          <div>
            <FieldLabel htmlFor="pool-sec">Khóa API mới</FieldLabel>
            <div className="relative">
              <TextInput
                id="pool-sec"
                type={showPoolSecret ? "text" : "password"}
                value={poolSecret}
                onChange={(e) => setPoolSecret(e.target.value)}
                placeholder="Dán khóa API..."
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowPoolSecret((v) => !v)}
                aria-label={showPoolSecret ? "Ẩn khóa" : "Hiện khóa"}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
              >
                {showPoolSecret ? (
                  <EyeOff className="w-4 h-4" />
                ) : (
                  <Eye className="w-4 h-4" />
                )}
              </button>
            </div>
          </div>
          <Button type="button" variant="emerald" onClick={() => void addPoolKey()}>
            <Plus className="w-4 h-4" /> Thêm vào Bể
          </Button>
        </div>

        {poolKeys.length === 0 ? (
          <EmptyState
            title="Chưa có khóa nào trong bể xoay vòng"
            description="Thêm nhiều khóa Gemini hoặc Claude để tự động luân phiên khi chạm giới hạn tần suất."
          />
        ) : (
          <div className="space-y-2">
            {poolKeys.map((k) => (
              <div
                key={k.id}
                className="flex items-center justify-between gap-2 rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3.5 py-2.5"
              >
                <div className="flex flex-wrap items-center gap-2 text-[13px]">
                  <Badge tone="sky" className="uppercase">
                    {k.provider}
                  </Badge>
                  <strong className="text-[var(--text-primary)]">
                    {k.label || `Khóa #${k.id}`}
                  </strong>
                  <span className="font-mono text-[12px] text-[var(--text-muted)]">
                    ({k.masked_preview})
                  </span>
                  <span className="text-[12px] text-[var(--text-muted)] tabular-nums">
                    • Đã gọi: {k.use_count} lần
                  </span>
                  {k.is_cooling_down && (
                    <Badge tone="amber">Đang nghỉ hồi hạn mức</Badge>
                  )}
                </div>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={`Xóa khóa ${k.label || k.id}`}
                  onClick={async () => {
                    await apiFetch(`/api/v1/key-pool/${k.id}`, {
                      method: "DELETE",
                    });
                    await onReload();
                  }}
                >
                  <Trash2 className="w-4 h-4 text-rose-400" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
