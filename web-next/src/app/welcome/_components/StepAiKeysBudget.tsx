"use client";

import React, { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Card, SectionHeading } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextInput } from "@/components/ui/form-controls";

export function StepAiKeysBudget({
  configuredSecrets,
  dailyUsd,
  setDailyUsd,
  apiFallback,
  setApiFallback,
  geminiKey,
  setGeminiKey,
  anthropicKey,
  setAnthropicKey,
  apifyToken,
  setApifyToken,
  onBack,
  onNext,
}: {
  configuredSecrets: string[];
  dailyUsd: number;
  setDailyUsd: (v: number) => void;
  apiFallback: string;
  setApiFallback: (v: string) => void;
  geminiKey: string;
  setGeminiKey: (v: string) => void;
  anthropicKey: string;
  setAnthropicKey: (v: string) => void;
  apifyToken: string;
  setApifyToken: (v: string) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const [showKeys, setShowKeys] = useState(false);

  return (
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
        {configuredSecrets.join(", ") ||
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
        <Button type="button" variant="secondary" onClick={onBack}>
          ← Quay lại
        </Button>
        <Button type="button" onClick={onNext}>
          Tiếp tục: Giọng đọc →
        </Button>
      </div>
    </Card>
  );
}
