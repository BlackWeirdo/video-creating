import * as React from "react";
import { cn } from "@/lib/utils";

export type PillTone = "cluster" | "emerald" | "amber" | "sky" | "rose" | "neutral";

const TONE_MAP: Record<PillTone, string> = {
  cluster: "bg-[var(--c-soft)] border-[var(--c-bd)] text-[var(--c-tx)]",
  emerald:
    "bg-[var(--st-emerald-bg)] border-[var(--st-emerald-bd)] text-[var(--st-emerald-tx)]",
  amber:
    "bg-[var(--st-amber-bg)] border-[var(--st-amber-bd)] text-[var(--st-amber-tx)]",
  sky: "bg-[var(--st-sky-bg)] border-[var(--st-sky-bd)] text-[var(--st-sky-tx)]",
  rose: "bg-[var(--st-rose-bg)] border-[var(--st-rose-bd)] text-[var(--st-rose-tx)]",
  neutral:
    "bg-[var(--bg-elevated)] border-[var(--border-subtle)] text-[var(--text-secondary)]",
};

export interface StatusPillProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: PillTone;
}

export function Badge({
  tone = "neutral",
  className,
  ...props
}: StatusPillProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] font-semibold whitespace-nowrap shrink-0",
        TONE_MAP[tone],
        className
      )}
      {...props}
    />
  );
}
