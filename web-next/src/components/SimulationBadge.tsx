"use client";

import React from "react";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";

const FLAG_LABELS: Record<string, string> = {
  tts_tone_placeholder: "Giọng đọc kiểm thử (chưa dùng Edge TTS / VieNeu thật)",
  audio_sep_midside_fallback: "Tách nhạc Mid/Side cơ bản (chưa cài UVR MDX-Net ONNX)",
  asr_silencedetect_placeholder: "Tách đoạn theo khoảng lặng (chưa cài Faster-Whisper)",
  translation_pending: "Chưa dịch bằng AI / NLLB (đang giữ nguyên lời gốc để sửa tay)",
  offline_nllb_translation: "Dịch máy offline NLLB-200 (CC-BY-NC) — nên kiểm tra lại câu chữ",
  diarization_single_speaker_fallback: "Gộp 1 người nói mặc định (chưa cài model phân biệt người nói ONNX)",
  ocr_inpaint_delogo_fallback: "Xóa chữ vùng cố định Delogo (chưa cài LaMa ONNX Inpaint)",
  ai_image_canvas_placeholder: "Khung nền đồ họa FFmpeg (chưa kết nối model sinh ảnh AI)",
  cutout_colorkey_fallback: "Tách nền theo màu (chưa cài Rembg U2Net)",
  lipsync_waveform_preview: "Bản xem trước sóng âm chân dung (chưa chạy nhép môi AI)",
};

export function SimulationBadge({ flags }: { flags?: string[] | null }) {
  if (!flags || flags.length === 0) return null;

  return (
    <div className="bg-amber-500/10 border border-amber-500/35 text-amber-200 rounded-lg px-3 py-2 text-[11px] space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 font-semibold text-amber-300">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" /> Chế độ mô phỏng / Dự phòng
        </span>
        <Link href="/settings" className="text-sky-300 hover:underline font-medium">
          Cài đặt Model &amp; AI Keys →
        </Link>
      </div>
      <ul className="list-disc list-inside text-amber-200/90 space-y-0.5">
        {flags.map((f) => (
          <li key={f}>{FLAG_LABELS[f] || f}</li>
        ))}
      </ul>
    </div>
  );
}
