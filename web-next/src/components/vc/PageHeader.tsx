import * as React from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export interface PipelineStepItem {
  title: string;
  subtitle?: string;
  state: "done" | "active" | "idle";
}

export function PageHeader({
  icon,
  title,
  description,
  badges,
  actions,
  steps,
}: {
  icon: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  badges?: React.ReactNode;
  actions?: React.ReactNode;
  steps?: PipelineStepItem[];
}) {
  return (
    <section
      className="rounded-[16px] border border-[var(--c-bd)] p-5 shadow-[var(--c-glow)] space-y-4"
      style={{ background: "var(--c-grad)" }}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3.5 min-w-0">
          <div
            aria-hidden="true"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px] border border-[var(--c-bd)] bg-[var(--c-soft)] text-[var(--c-icon)]"
          >
            {icon}
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-[21px] md:text-[22px] font-bold tracking-tight text-[var(--text-primary)] leading-tight">
                {title}
              </h1>
              {badges}
            </div>
            {description && (
              <p className="mt-1 text-[13.5px] text-[var(--text-secondary)] max-w-[70ch]">
                {description}
              </p>
            )}
          </div>
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>

      {steps && steps.length > 0 && (
        <div
          role="list"
          aria-label="Các bước quy trình"
          className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2"
        >
          {steps.map((s, idx) => (
            <div
              key={idx}
              role="listitem"
              className={cn(
                "flex items-center gap-2.5 rounded-[10px] border px-3 py-2 text-[12.5px]",
                s.state === "active"
                  ? "border-[var(--c-bd)] bg-[var(--c-soft)] text-[var(--c-tx)] font-semibold"
                  : s.state === "done"
                    ? "border-[var(--st-emerald-bd)] bg-[var(--bg-card)]/85 text-[var(--text-primary)]"
                    : "border-[var(--border-subtle)] bg-[var(--bg-card)]/80 text-[var(--text-secondary)]"
              )}
            >
              <span
                className={cn(
                  "inline-flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full text-[11.5px] font-bold tabular-nums",
                  s.state === "active"
                    ? "bg-[var(--c-solid)] text-[var(--c-on)]"
                    : s.state === "done"
                      ? "bg-[var(--st-emerald-bg)] text-[var(--st-emerald-tx)]"
                      : "bg-[var(--bg-elevated)] text-[var(--text-muted)]"
                )}
              >
                {s.state === "done" ? <Check className="w-3.5 h-3.5" /> : idx + 1}
              </span>
              <div className="min-w-0">
                <div className="truncate font-semibold">{s.title}</div>
                {s.subtitle && (
                  <div className="truncate text-[11.5px] text-[var(--text-muted)] font-normal">
                    {s.subtitle}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
