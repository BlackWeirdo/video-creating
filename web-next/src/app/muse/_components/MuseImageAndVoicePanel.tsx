"use client";

import React, { useState } from "react";
import { Image as ImageIcon, Mic } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { useApiMutation } from "@/hooks/useApiMutation";
import { Card, SectionHeading } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  TextareaBox,
} from "@/components/ui/form-controls";

const MUSE_VI_VOICES = [
  "Glad Kite",
  "Breathless Rosette",
  "Sparkling Whistle",
  "Kindhearted Jetty",
  "Questioning Satchel",
  "Tenacious Mooring",
  "Zealous Harbor",
];

export function MuseImageAndVoicePanel({
  workspaceId,
  onCreated,
  onError,
}: {
  workspaceId: number;
  onCreated: () => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [imgPrompt, setImgPrompt] = useState("");
  const [imgCount, setImgCount] = useState(4);
  const [imgRatio, setImgRatio] = useState("9:16");

  const [ttsText, setTtsText] = useState("");
  const [voice, setVoice] = useState("Glad Kite");

  const { mutate: queueImage, mutating: imgBusy } = useApiMutation(
    async () => {
      await apiFetch("/api/v1/muse/tasks", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId,
          kind: "image",
          prompt: imgPrompt,
          count: imgCount,
          ratio: imgRatio,
        }),
      });
      void apiFetch("/api/v1/muse/dispatch", { method: "POST" }).catch(() => {});
    },
    {
      onError,
      onSuccess: async () => {
        setImgPrompt("");
        toast.success(`Đã xếp tạo ${imgCount} ảnh Muse vào hàng chờ!`);
        await onCreated();
      },
    }
  );

  const { mutate: queueVoice, mutating: ttsBusy } = useApiMutation(
    async () => {
      await apiFetch("/api/v1/muse/tasks", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId,
          kind: "audio",
          prompt: ttsText,
          voice,
          language: "Vietnamese",
        }),
      });
      void apiFetch("/api/v1/muse/dispatch", { method: "POST" }).catch(() => {});
    },
    {
      onError,
      onSuccess: async () => {
        setTtsText("");
        toast.success("Đã xếp tạo bản thu giọng đọc Muse!");
        await onCreated();
      },
    }
  );

  return (
    <div className="grid md:grid-cols-2 gap-4">
      <Card tinted>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void queueImage();
          }}
          className="space-y-3.5"
        >
          <SectionHeading>
            <ImageIcon className="w-4 h-4 text-[var(--c-icon)]" /> Sinh Lô Ảnh Muse (1–4 ảnh / lần)
          </SectionHeading>
          <div>
            <FieldLabel htmlFor="mi-prompt">Mô tả khung ảnh *</FieldLabel>
            <TextareaBox
              id="mi-prompt"
              required
              rows={3}
              value={imgPrompt}
              onChange={(e) => setImgPrompt(e.target.value)}
              placeholder="VD: Góc bàn làm việc tối giản ánh sáng tự nhiên..."
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <FieldLabel htmlFor="mi-cnt">Số ảnh sinh ra</FieldLabel>
              <SelectBox
                id="mi-cnt"
                value={imgCount}
                onChange={(e) => setImgCount(Number(e.target.value))}
              >
                <option value={1}>1 ảnh</option>
                <option value={2}>2 ảnh</option>
                <option value={4}>4 biến thể ảnh</option>
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="mi-ratio">Tỷ lệ</FieldLabel>
              <SelectBox
                id="mi-ratio"
                value={imgRatio}
                onChange={(e) => setImgRatio(e.target.value)}
              >
                <option value="9:16">9:16 Dọc</option>
                <option value="16:9">16:9 Ngang</option>
                <option value="1:1">1:1 Vuông</option>
              </SelectBox>
            </div>
          </div>
          <Button type="submit" disabled={imgBusy}>
            {imgBusy ? "Đang xếp hàng..." : `Tạo ${imgCount} Ảnh Muse`}
          </Button>
        </form>
      </Card>

      <Card>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void queueVoice();
          }}
          className="space-y-3.5"
        >
          <SectionHeading>
            <Mic className="w-4 h-4 text-[var(--c-icon)]" /> Thu Giọng Đọc Muse Voice (WAV 48kHz)
          </SectionHeading>
          <div>
            <FieldLabel htmlFor="mv-voice">Giọng đọc Tiếng Việt</FieldLabel>
            <SelectBox
              id="mv-voice"
              value={voice}
              onChange={(e) => setVoice(e.target.value)}
            >
              {MUSE_VI_VOICES.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </SelectBox>
          </div>
          <div>
            <FieldLabel htmlFor="mv-txt">Lời thoại cần đọc (≤ 6.000 ký tự) *</FieldLabel>
            <TextareaBox
              id="mv-txt"
              required
              rows={3}
              value={ttsText}
              onChange={(e) => setTtsText(e.target.value)}
              placeholder="Nhập lời dẫn hoặc kịch bản tiếng Việt..."
            />
          </div>
          <Button type="submit" variant="secondary" disabled={ttsBusy}>
            {ttsBusy ? "Đang xếp hàng..." : "Thu Giọng Muse"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
