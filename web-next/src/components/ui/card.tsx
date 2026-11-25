import * as React from "react";
import { cn } from "@/lib/utils";

export interface SurfaceCardProps extends React.HTMLAttributes<HTMLDivElement> {
  tinted?: boolean;
}

export function Card({ className, tinted = false, ...props }: SurfaceCardProps) {
  return (
    <div
      className={cn(
        "rounded-[14px] border p-4 md:p-5 transition-colors duration-150",
        tinted
          ? "border-[var(--c-bd)] bg-[linear-gradient(180deg,var(--c-soft)_0%,transparent_120px),var(--bg-card)] shadow-[var(--shadow-sm)]"
          : "border-[var(--border-subtle)] bg-[var(--bg-card)] shadow-[var(--shadow-sm)]",
        className
      )}
      {...props}
    />
  );
}

export function CardTitleRow({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("flex flex-wrap items-center justify-between gap-2.5", className)}
      {...props}
    />
  );
}

export function SectionHeading({
  className,
  ...props
}: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      className={cn(
        "text-[15.5px] font-bold tracking-tight text-[var(--text-primary)] flex items-center gap-2",
        className
      )}
      {...props}
    />
  );
}
