"use client";

import React from "react";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";

const FLAG_LABELS: Record<string, string> = {
  tts_tone_placeholder: "Giọng đọc kiểm thử (chưa dùng Edge TTS / VieNeu thật)",
  audio_sep_midside_fallback: "Tách nhạc Mid/Side cơ bản (chưa cài UVR MDX-Net ONNX)",
  asr_silencedetect_placeholder: "Tách đoạn theo khoảng lặng (chưa cài Faster-Whisper)",
  translation_pending: "Chưa dịch bằng AI / NLLB (đang giữ nguyên lời gốc để sửa tay)",
  offline_nllb_translation: "Dịch máy nội bộ NLLB-200 (CC-BY-NC) — nên kiểm tra lại câu chữ",
  diarization_single_speaker_fallback:
    "Gộp 1 người nói mặc định (chưa cài model phân biệt người nói ONNX)",
  ocr_inpaint_delogo_fallback: "Xóa chữ vùng cố định Delogo (chưa cài LaMa ONNX Inpaint)",
  ai_image_canvas_placeholder: "Khung nền đồ họa FFmpeg (chưa kết nối model sinh ảnh AI)",
  cutout_colorkey_fallback: "Tách nền theo màu (chưa cài Rembg U2Net)",
  lipsync_waveform_preview: "Bản xem trước sóng âm chân dung (chưa chạy nhép môi AI)",
};

export function SimulationBadge({ flags }: { flags?: string[] | null }) {
  if (!flags || flags.length === 0) return null;

  return (
    <div className="rounded-[11px] border border-[var(--st-amber-bd)] bg-[var(--st-amber-bg)] px-3.5 py-2.5 text-[12.5px] text-[var(--st-amber-tx)] space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 font-semibold">
          <AlertTriangle className="w-4 h-4 shrink-0" /> Minh bạch AI — Đang dùng đường dự phòng
        </span>
        <Link href="/settings" className="underline font-semibold hover:opacity-85">
          Cài đặt Mô hình &amp; AI Keys →
        </Link>
      </div>
      <ul className="list-disc list-inside space-y-0.5 opacity-95">
        {flags.map((f) => (
          <li key={f}>{FLAG_LABELS[f] || f}</li>
        ))}
      </ul>
    </div>
  );
}
