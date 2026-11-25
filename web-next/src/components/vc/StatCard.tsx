import * as React from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

export function StatCard({
  title,
  value,
  subtitle,
  href,
  icon,
  accentStyle,
}: {
  title: string;
  value: React.ReactNode;
  subtitle?: React.ReactNode;
  href?: string;
  icon?: React.ReactNode;
  accentStyle?: React.CSSProperties;
}) {
  const inner = (
    <div
      style={accentStyle}
      className={cn(
        "rounded-[14px] border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 shadow-[var(--shadow-sm)] transition-all duration-150",
        href && "hover:border-[var(--c-bd)] hover:-translate-y-0.5 cursor-pointer"
      )}
    >
      <div className="flex items-center justify-between gap-2 text-[12.5px] font-medium text-[var(--text-muted)]">
        <span>{title}</span>
        {icon && <span className="text-[var(--c-icon)]">{icon}</span>}
      </div>
      <div className="mt-2 text-[24px] font-bold tracking-tight text-[var(--text-primary)] tabular-nums">
        {value}
      </div>
      {subtitle && (
        <div className="mt-1 text-[12px] text-[var(--text-muted)]">{subtitle}</div>
      )}
    </div>
  );
  return href ? <Link href={href}>{inner}</Link> : inner;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[13px] border border-dashed border-[var(--border-strong)] bg-[var(--bg-elevated)]/60 px-6 py-8 text-center">
      {icon && (
        <div className="mb-2.5 flex h-10 w-10 items-center justify-center rounded-full bg-[var(--c-soft)] text-[var(--c-icon)]">
          {icon}
        </div>
      )}
      <div className="text-[14px] font-semibold text-[var(--text-primary)]">{title}</div>
      {description && (
        <p className="mt-1 max-w-md text-[13px] text-[var(--text-muted)]">{description}</p>
      )}
      {action && <div className="mt-3.5">{action}</div>}
    </div>
  );
}
