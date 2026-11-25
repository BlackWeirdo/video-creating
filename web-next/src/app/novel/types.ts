export interface NovelChapter {
  id: number;
  chapter_index: number;
  title: string;
  word_count: number;
  status: string;
  video_id: number | null;
  output_path: string;
  video_url: string;
}

export interface NovelProject {
  id: number;
  title: string;
  aspect_ratio: string;
  style_preset: string;
  voice_id?: string;
  status: string;
  total_chapters: number;
  ready_chapters: number;
  chapters: NovelChapter[];
  simulation_flags?: string[];
}

export const BASE_NOVEL_VOICES = [
  { value: "vi-VN-HoaiMyNeural", label: "Edge TTS: Hoài My (Nữ)" },
  { value: "vi-VN-NamMinhNeural", label: "Edge TTS: Nam Minh (Nam)" },
  { value: "vieneu:Mỹ Duyên", label: "VieNeu CPU: Mỹ Duyên (Nữ đọc truyện)" },
  { value: "vieneu:Đức Trí", label: "VieNeu CPU: Đức Trí (Nam đọc truyện)" },
  { value: "vieneu:Anh Khôi", label: "VieNeu CPU: Anh Khôi (Nam kể chuyện)" },
  { value: "vieneu:Trúc Ly", label: "VieNeu CPU: Trúc Ly (Nữ tự nhiên)" },
];
