export interface LocalizeSegment {
  index: number;
  start_s: number;
  end_s: number;
  source_text: string;
  translated_text: string;
  speaker_id?: string;
  text_origin?: string;
  syllable_count?: number;
  syllable_budget?: number;
  replace_shot_id: number;
  preview_audio_url?: string;
}

export interface SpeakerEntry {
  label: string;
  provider: string;
  voice_id: string;
  ref_audio_rel?: string;
}

export interface OcrCue {
  start_s: number;
  end_s: number;
  text: string;
  confidence: number;
  box: { x: number; y: number; w: number; h: number };
}

export interface LocalizeProject {
  id: number;
  title: string;
  mode: "reup_vi" | "hybrid_remix" | "intl_export";
  source_lang: string;
  target_lang: string;
  hardsub_mode: "none" | "blur_bar" | "crop_frame" | "ocr_inpaint";
  hardsub_box: { x: number; y: number; w: number; h: number };
  style_preset: string;
  aspect_ratio: string;
  whisper_size?: "small" | "medium";
  translation_style?: "natural_tiktok" | "literal";
  clone_source_voice?: boolean;
  clone_consent_confirmed?: boolean;
  speaker_config?: { speakers?: Record<string, SpeakerEntry>; trans_engine?: string };
  ocr_cues?: OcrCue[];
  status: string;
  output_video_id: number | null;
  error: string | null;
  segments: LocalizeSegment[];
  simulation_flags?: string[];
}

export interface ShotRow {
  id: number;
  description: string;
  has_product: number;
}

export const SPEAKER_VOICE_OPTIONS = [
  { provider: "edge", voice_id: "vi-VN-HoaiMyNeural", label: "Edge TTS: Hoài My (Nữ)" },
  { provider: "edge", voice_id: "vi-VN-NamMinhNeural", label: "Edge TTS: Nam Minh (Nam)" },
  { provider: "vieneu", voice_id: "Trúc Ly", label: "VieNeu CPU: Trúc Ly (Nữ Bắc)" },
  { provider: "vieneu", voice_id: "Minh Quân", label: "VieNeu CPU: Minh Quân (Nam Bắc)" },
  { provider: "vieneu", voice_id: "Ái Hân", label: "VieNeu CPU: Ái Hân (Nữ Nam)" },
  { provider: "vieneu", voice_id: "Adam", label: "VieNeu CPU: Adam (Nam Nam)" },
  { provider: "vieneu", voice_id: "Mỹ Duyên", label: "VieNeu CPU: Mỹ Duyên (Kể chuyện)" },
  { provider: "vieneu", voice_id: "Đức Trí", label: "VieNeu CPU: Đức Trí (Đọc truyện)" },
  { provider: "edge", voice_id: "en-US-JennyNeural", label: "Edge TTS: Jenny (EN)" },
  { provider: "edge", voice_id: "en-US-GuyNeural", label: "Edge TTS: Guy (EN)" },
];
