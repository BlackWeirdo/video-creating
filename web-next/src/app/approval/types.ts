export type SocialPlatform =
  | "facebook"
  | "instagram"
  | "threads"
  | "tiktok"
  | "youtube";

export interface ApprovalVideo {
  id: number;
  status: string;
  aspect_ratio: string;
  style_preset: string;
  duration_s: number | null;
  output_url: string | null;
  quality_score: number | null;
  unsupported_claims: string[];
  plan: { title?: string };
  qc: { passed?: boolean; issues?: string[] };
}

export interface ChannelAccount {
  id: number;
  platform: string;
  external_id: string;
  name: string;
  lang: string;
  approval_mode: string;
  autopilot_min_score: number;
  slots: string[];
  enabled: boolean;
  has_token: boolean;
}

export interface PostItem {
  id: number;
  video_id: number;
  platform: string;
  account_name: string;
  status: string;
  scheduled_at: string;
  permalink: string | null;
  error: string | null;
}

export interface PerfItem {
  post_id: number;
  video_id: number;
  title: string;
  platform: string;
  account_name: string;
  checkpoints: Record<
    string,
    { views?: number | null; likes?: number | null; comments?: number | null } | null
  >;
}
