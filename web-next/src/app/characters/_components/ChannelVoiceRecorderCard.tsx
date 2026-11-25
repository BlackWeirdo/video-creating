"use client";

import React, { useRef, useState } from "react";
import { Mic, Square, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import type { ChannelVoiceRow, CharacterRow } from "@/app/characters/types";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  SwitchToggle,
  TextInput,
} from "@/components/ui/form-controls";

export function ChannelVoiceRecorderCard({
  workspaceId,
  characters,
  channelVoices,
  onReload,
  onMessage,
  onError,
}: {
  workspaceId: number;
  characters: CharacterRow[];
  channelVoices: ChannelVoiceRow[];
  onReload: () => Promise<void>;
  onMessage: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [cvName, setCvName] = useState("");
  const [cvSpeaker, setCvSpeaker] = useState("");
  const [cvCharId, setCvCharId] = useState<number>(0);
  const [cvConsent, setCvConsent] = useState(false);
  const [cvFile, setCvFile] = useState<File | null>(null);
  const [recording, setRecording] = useState(false);
  const mediaRecRef = useRef<MediaRecorder | null>(null);
  const recChunksRef = useRef<BlobPart[]>([]);

  const startMicRecord = async () => {
    onError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recChunksRef.current = [];
      const mr = new MediaRecorder(stream);
      mr.ondataavailable = (ev) => {
        if (ev.data.size > 0) recChunksRef.current.push(ev.data);
      };
      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(recChunksRef.current, { type: "audio/webm" });
        setCvFile(new File([blob], "mc_recorded.webm", { type: "audio/webm" }));
        onMessage(
          "Đã thu xong mẫu giọng! Hãy bật xác nhận đồng ý rồi bấm Lưu Giọng Kênh."
        );
      };
      mediaRecRef.current = mr;
      mr.start();
      setRecording(true);
    } catch {
      onError(
        "Không truy cập được Microphone — bạn có thể chọn tệp âm thanh mẫu (.wav / .mp3)."
      );
    }
  };

  const stopMicRecord = () => {
    if (mediaRecRef.current && mediaRecRef.current.state !== "inactive") {
      mediaRecRef.current.stop();
    }
    setRecording(false);
  };

  const saveChannelVoice = async (e: React.FormEvent) => {
    e.preventDefault();
    onError("");
    onMessage("");
    if (!cvFile) {
      onError("Hãy thu âm bằng Mic (5–10 giây) hoặc chọn tệp âm thanh mẫu trước.");
      return;
    }
    try {
      const fd = new FormData();
      fd.append("file", cvFile);
      fd.append("name", cvName);
      fd.append("speaker_name", cvSpeaker);
      fd.append("consent_confirmed", cvConsent ? "true" : "false");
      fd.append("workspace_id", String(workspaceId));
      if (cvCharId > 0) fd.append("character_id", String(cvCharId));

      await apiFetch("/api/v1/channel-voices", { method: "POST", body: fd });
      setCvName("");
      setCvSpeaker("");
      setCvConsent(false);
      setCvFile(null);
      const m = "Đã lưu Giọng Kênh MC (VieNeu-TTS CPU) cho Workspace!";
      onMessage(m);
      toast.success(m);
      await onReload();
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Không thể lưu Giọng kênh");
    }
  };

  return (
    <Card className="space-y-4">
      <SectionHeading>
        <Mic className="w-4 h-4 text-[var(--c-icon)]" /> Thư viện Giọng Kênh MC (Thu mẫu 5–10 giây • VieNeu CPU)
      </SectionHeading>

      <form onSubmit={saveChannelVoice} className="space-y-3.5">
        <div className="grid md:grid-cols-4 gap-3 items-end">
          <div>
            <FieldLabel htmlFor="cv-name">Tên giọng kênh *</FieldLabel>
            <TextInput
              id="cv-name"
              required
              value={cvName}
              onChange={(e) => setCvName(e.target.value)}
              placeholder="VD: Giọng Kênh Bảo Ngọc"
            />
          </div>
          <div>
            <FieldLabel htmlFor="cv-spk">Họ tên MC đồng ý *</FieldLabel>
            <TextInput
              id="cv-spk"
              required
              value={cvSpeaker}
              onChange={(e) => setCvSpeaker(e.target.value)}
              placeholder="Họ tên người thu mẫu"
            />
          </div>
          <div>
            <FieldLabel htmlFor="cv-chr">Gắn mặc định cho nhân vật</FieldLabel>
            <SelectBox
              id="cv-chr"
              value={cvCharId}
              onChange={(e) => setCvCharId(Number(e.target.value))}
            >
              <option value={0}>Dùng chung toàn Workspace</option>
              {characters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </SelectBox>
          </div>
          <div className="flex gap-2">
            {!recording ? (
              <Button
                type="button"
                variant="danger"
                onClick={() => void startMicRecord()}
              >
                <Mic className="w-4 h-4" /> Thu Mic
              </Button>
            ) : (
              <Button type="button" variant="danger" onClick={stopMicRecord}>
                <Square className="w-4 h-4" /> Dừng thu
              </Button>
            )}
            <label className="inline-flex min-h-[38px] items-center gap-1.5 rounded-[9px] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 py-1.5 text-[13px] font-semibold text-[var(--text-primary)] hover:border-[var(--c-bd)] cursor-pointer">
              <Upload className="w-4 h-4 text-[var(--c-icon)]" /> Tệp mẫu
              <input
                type="file"
                accept=".wav,.mp3,.m4a,.webm,.ogg"
                className="sr-only"
                onChange={(e) => setCvFile(e.target.files?.[0] || null)}
              />
            </label>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
          <div className="flex items-center gap-2.5">
            <SwitchToggle
              id="cv-consent"
              checked={cvConsent}
              onCheckedChange={setCvConsent}
            />
            <label
              htmlFor="cv-consent"
              className="text-[13px] text-[var(--text-secondary)] cursor-pointer"
            >
              Xác nhận MC / chủ giọng thuộc công ty và đã đồng ý nhân bản giọng cho kênh này.
              {cvFile && (
                <Badge tone="emerald" className="ml-2">
                  {cvFile.name}
                </Badge>
              )}
            </label>
          </div>
          <Button type="submit" variant="emerald">
            Lưu Giọng Kênh
          </Button>
        </div>
      </form>

      {channelVoices.length > 0 && (
        <div className="grid md:grid-cols-2 gap-3 pt-2">
          {channelVoices.map((cv) => (
            <div
              key={cv.id}
              className="rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 space-y-2"
            >
              <div className="flex items-center justify-between gap-2">
                <div>
                  <strong className="text-[13.5px] text-[var(--text-primary)]">
                    {cv.name}
                  </strong>{" "}
                  <span className="text-[12px] text-[var(--text-muted)] tabular-nums">
                    ({cv.speaker_name} • {cv.duration_s}s)
                  </span>
                </div>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={`Xóa giọng ${cv.name}`}
                  onClick={async () => {
                    await apiFetch(`/api/v1/channel-voices/${cv.id}`, {
                      method: "DELETE",
                    });
                    await onReload();
                  }}
                >
                  <Trash2 className="w-4 h-4 text-rose-400" />
                </Button>
              </div>
              {cv.audio_url && (
                <audio controls src={cv.audio_url} className="h-8 w-full" />
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
