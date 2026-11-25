export interface MuseModelOption {
  id: string;
  kind: "chat" | "image" | "video" | "audio";
}

export interface MuseCombo {
  id: string;
  name: string;
  accountIds: string[];
  strategy: "round-robin" | "fallback" | "fusion";
  kind?: "chat" | "image" | "video" | "audio";
}

export interface MusePoolAccount {
  id: string;
  name: string;
  enabled: boolean;
  status: string;
  cooldown_remaining_ms: number;
  cooldown_reason: string;
  lanes: number | unknown[];
  last_status: string;
  last_tested?: string | null;
  proxy?: string | null;
}

export interface MuseStatus {
  enabled: boolean;
  mode: "local_sidecar" | "remote";
  base_url: string;
  paired: boolean;
  online: boolean;
  hardened: boolean;
  unsafe_error: string;
  version: string;
  sidecar: {
    owned: boolean;
    pid: number | null;
    entry_found: boolean;
    entry_path: string;
    unsafe_error: string;
    last_error: string;
  };
  accounts: {
    total: number;
    ready: number;
    busy: number;
    cooldown: number;
  };
  capacity: number;
  queue: {
    pending: number;
    submitted: number;
    importing: number;
    waiting_quota: number;
    running_total: number;
  };
  today: {
    videos_succeeded: number;
    videos_failed: number;
    success_rate: number;
  };
}

export interface MuseRefDescriptor {
  type: "character" | "product" | "ai_image" | "upload" | "footage_frame" | "trend_clip";
  id?: number;
  upload_id?: string;
  real_face?: boolean;
  face_consent_confirmed?: boolean;
  rights_confirmed?: boolean;
}

export interface MuseTask {
  id: number;
  workspace_id: number;
  kind: "video" | "image" | "audio" | "chat";
  model: string;
  purpose: string;
  prompt: string;
  params: {
    duration?: number;
    ratio?: string;
    count?: number;
    voice?: string;
    language?: string;
    speed?: number;
  };
  refs: MuseRefDescriptor[];
  thread_url: string | null;
  account_id: string | null;
  parent_task_id: number | null;
  status:
    | "pending"
    | "submitted"
    | "importing"
    | "succeeded"
    | "failed"
    | "cancelled"
    | "waiting_quota";
  attempt: number;
  gateway_task_id: string | null;
  partial: boolean;
  duration_sec: number | null;
  local_path: string | null;
  media_url: string;
  shot_id: number | null;
  ai_image_id: number | null;
  asset_id: number | null;
  error: string | null;
  retry_after: string | null;
  created_at: string;
}

export interface MuseStoryboardSegment {
  id: number;
  storyboard_id: number;
  idx: number;
  prompt: string;
  duration_sec: number;
  caption: string;
  status: string;
  muse_task_id: number | null;
  task: MuseTask | null;
}

export interface MuseStoryboard {
  id: number;
  workspace_id: number;
  title: string;
  ratio: string;
  model: string;
  continuity: boolean;
  narration: { voice_id?: string; lang?: string };
  style_preset: string;
  status: string;
  output_video_id: number | null;
  simulation_flags: string[];
  error: string | null;
  segments: MuseStoryboardSegment[];
}
