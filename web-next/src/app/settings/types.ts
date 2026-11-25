export interface LocalModelRow {
  model_id: string;
  name: string;
  category: string;
  size_mb: number;
  status: string;
  progress: number;
  installed_on_disk: boolean;
  license?: string;
  smoke_tested?: boolean;
  missing_python_pkgs?: string[];
  error?: string | null;
}

export interface PooledKeyRow {
  id: number;
  provider: string;
  label: string;
  masked_preview: string;
  enabled: boolean;
  priority: number;
  is_cooling_down: boolean;
  use_count: number;
}

export interface BackupSummary {
  db_size_bytes: number;
  workspaces: number;
  products: number;
  workflows: number;
  channels: number;
  pooled_keys: number;
  secrets_count: number;
  snapshots: Array<{ filename: string; size_bytes: number }>;
}

export interface SecretMeta {
  name: string;
  label: string;
  configured: boolean;
}

export interface VoiceOption {
  provider: string;
  lang: string;
  voice: string;
  label: string;
}
