"use client";

import React from "react";
import { Rocket } from "lucide-react";
import { Card, SectionHeading } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextInput } from "@/components/ui/form-controls";

export function StepVoiceFinish({
  viProvider,
  setViProvider,
  viVoice,
  setViVoice,
  timezone,
  setTimezone,
  saving,
  onBack,
  onFinish,
}: {
  viProvider: string;
  setViProvider: (v: string) => void;
  viVoice: string;
  setViVoice: (v: string) => void;
  timezone: string;
  setTimezone: (v: string) => void;
  saving: boolean;
  onBack: () => void;
  onFinish: () => Promise<void>;
}) {
  return (
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
        <Button type="button" variant="secondary" onClick={onBack}>
          ← Quay lại
        </Button>
        <Button
          type="button"
          variant="emerald"
          disabled={saving}
          onClick={() => void onFinish()}
        >
          <Rocket className="w-4 h-4" />{" "}
          {saving ? "Đang lưu cấu hình..." : "Hoàn Tất Thiết Lập"}
        </Button>
      </div>
    </Card>
  );
}
