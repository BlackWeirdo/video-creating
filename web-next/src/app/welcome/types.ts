import type { Workspace } from "@/lib/api/types";

export interface OnboardingStatus {
  wizard_completed: boolean;
  runtime: {
    ffmpeg_ready: boolean;
    ffprobe_ready: boolean;
    node_ready: boolean;
    ytdlp_ready: boolean;
    ffmpeg_path: string;
    node_path: string;
  };
  workspace_count: number;
  active_workspace_id: number;
  active_workspace: Workspace | null;
  configured_secrets: string[];
  key_pool_count: number;
  connected_channels_count: number;
  defaults: {
    role: string;
    daily_usd: number;
    api_fallback: string;
    timezone: string;
    vi_provider: string;
    vi_voice: string;
  };
}
