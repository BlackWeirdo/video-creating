export interface WatchItem {
  id: number;
  source: string;
  kind: string;
  value: string;
  enabled: number;
}

export interface TrendItem {
  id: number;
  source: string;
  title: string;
  url: string;
  score: number;
  analysis_status: string;
  analysis: Record<string, unknown> | null;
}

export interface SuggestionItem {
  id: number;
  text: string;
  status: string;
  formula: Record<string, unknown>;
}
