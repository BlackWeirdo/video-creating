export interface ProductOption {
  id: number;
  name: string;
  material: string;
}

export interface BatchItemRow {
  id: number;
  item_index: number;
  variant_label: string;
  style_preset: string;
  hook_angle: string;
  step: string;
  video_id: number | null;
  video_status: string | null;
  video_quality_score: number | null;
  error: string | null;
}

export interface BatchRunRow {
  id: number;
  title: string;
  source_kind: string;
  ab_count: number;
  status: string;
  total_items?: number;
  completed_items?: number;
  failed_items?: number;
  items?: BatchItemRow[];
}
