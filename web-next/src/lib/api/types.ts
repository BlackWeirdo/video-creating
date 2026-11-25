export interface Workspace {
  id: number;
  slug: string;
  name: string;
  niche: string;
  content_policy: "strict_footage" | "hybrid_remix" | "full_ai";
  approval_mode: "single" | "bulk" | "autopilot";
  default_aspect_ratio: "9:16" | "16:9" | "1:1";
  style_preset: string;
  archived: boolean;
}

export interface QueueSummary {
  paused: boolean;
  by_status: Record<string, number>;
  by_lane: {
    io: Record<string, number>;
    compute: Record<string, number>;
  };
}

export interface JobRecord {
  id: number;
  workspace_id: number;
  kind: string;
  lane: "io" | "compute";
  status: string;
  progress: number;
  step: string;
  attempts?: number;
  error: string | null;
  log_tail: string | null;
}

export interface NavCounts {
  approvals_pending: number;
  suggestions_new: number;
  failed_routes: string[];
}

export interface MuseQueueSnapshot {
  pending: number;
  submitted: number;
  importing: number;
  waiting_quota: number;
  running_total: number;
}

export interface CharacterOption {
  id: number;
  name: string;
  voice_id: string;
}

export interface ChannelVoiceOption {
  id: number;
  name: string;
  speaker_name: string;
  voice_token: string;
}
