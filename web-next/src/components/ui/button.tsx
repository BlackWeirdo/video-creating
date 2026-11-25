import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";

export type ButtonVariant =
  | "primary"
  | "secondary"
  | "ghost"
  | "emerald"
  | "amber"
  | "danger";

export type ButtonSize = "md" | "sm" | "icon";

export interface StudioButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  asChild?: boolean;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-[var(--c-solid)] text-[var(--c-on)] border-transparent shadow-[var(--c-glow)] hover:brightness-105",
  secondary:
    "bg-[var(--bg-elevated)] text-[var(--text-primary)] border-[var(--border-strong)] hover:border-[var(--c-bd)]",
  ghost:
    "bg-transparent text-[var(--text-secondary)] border-transparent hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]",
  emerald:
    "bg-[var(--st-emerald-bg)] text-[var(--st-emerald-tx)] border-[var(--st-emerald-bd)] hover:brightness-105",
  amber:
    "bg-[var(--st-amber-bg)] text-[var(--st-amber-tx)] border-[var(--st-amber-bd)] hover:brightness-105",
  danger:
    "bg-[var(--st-rose-bg)] text-[var(--st-rose-tx)] border-[var(--st-rose-bd)] hover:brightness-105",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  md: "min-h-[38px] px-3.5 py-1.5 text-[13.5px] rounded-[9px] gap-2",
  sm: "min-h-[34px] px-2.5 py-1 text-[12.5px] rounded-[8px] gap-1.5",
  icon: "min-h-[34px] min-w-[34px] p-1.5 rounded-[8px] justify-center",
};

export const Button = React.forwardRef<HTMLButtonElement, StudioButtonProps>(
  (
    { className, variant = "primary", size = "md", asChild = false, ...props },
    ref
  ) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center font-semibold border cursor-pointer select-none transition-all duration-150 ease-out active:scale-[0.98] disabled:opacity-45 disabled:pointer-events-none",
          VARIANT_CLASSES[variant],
          SIZE_CLASSES[size],
          className
        )}
        {...props}
      />
    );
  }
);
Button.displayName = "StudioButton";
