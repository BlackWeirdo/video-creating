export interface CharacterRow {
  id: number;
  name: string;
  appearance_prompt: string;
  seed: number;
  voice_id: string;
  ref_image_path: string;
  cutout_image_path: string;
  cutout_simulation_flags?: string[];
}

export interface AIImageRow {
  id: number;
  character_id: number | null;
  prompt: string;
  seed: number;
  aspect_ratio: string;
  is_product_shot: boolean;
  image_path: string;
  cutout_path: string;
  motion_shot_id: number | null;
  simulation_flags?: string[];
}

export interface ChannelVoiceRow {
  id: number;
  name: string;
  speaker_name: string;
  character_id: number | null;
  duration_s: number;
  audio_url: string;
  voice_token: string;
}
