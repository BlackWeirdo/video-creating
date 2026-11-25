"use client";

import React from "react";
import { Sparkles } from "lucide-react";
import type { SuggestionItem } from "@/app/trends/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function SuggestionsList({
  suggestions,
  onAction,
}: {
  suggestions: SuggestionItem[];
  onAction: (id: number, action: "accept" | "dismiss") => Promise<void>;
}) {
  return (
    <div className="border-t border-[var(--border-subtle)] pt-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="inline-flex items-center gap-1.5 text-[13.5px] font-bold text-[var(--text-primary)]">
          <Sparkles className="w-4 h-4 text-[var(--c-icon)]" /> Đề xuất Ý tưởng ({suggestions.length})
        </span>
      </div>

      {suggestions.length === 0 ? (
        <p className="text-[12.5px] text-[var(--text-muted)]">
          Chưa có đề xuất kịch bản mới.
        </p>
      ) : (
        <div className="space-y-2 max-h-44 overflow-y-auto">
          {suggestions.map((s) => (
            <div
              key={s.id}
              className="rounded-[10px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 space-y-2 text-[13px]"
            >
              <div className="text-[var(--text-primary)]">{s.text}</div>
              <div className="flex items-center justify-between gap-2">
                <Badge tone="neutral">{s.status}</Badge>
                {["new", "sent"].includes(s.status) && (
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="emerald"
                      onClick={() => void onAction(s.id, "accept")}
                    >
                      Nhận ý tưởng
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => void onAction(s.id, "dismiss")}
                    >
                      Bỏ qua
                    </Button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
