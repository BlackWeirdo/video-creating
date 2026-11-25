"use client";

import * as React from "react";
import * as RadixLabel from "@radix-ui/react-label";
import * as RadixSwitch from "@radix-ui/react-switch";
import { cn } from "@/lib/utils";

export function FieldLabel({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof RadixLabel.Root>) {
  return (
    <RadixLabel.Root
      className={cn(
        "block text-[12.5px] font-medium text-[var(--text-secondary)] mb-1",
        className
      )}
      {...props}
    />
  );
}

export const TextInput = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "w-full min-h-[38px] rounded-[8px] border border-[var(--border-strong)] bg-[var(--bg-input)] px-3 py-1.5 text-[13.5px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-colors duration-150 focus:border-[var(--c-icon)] disabled:opacity-50",
      className
    )}
    {...props}
  />
));
TextInput.displayName = "TextInput";

export const TextareaBox = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "w-full rounded-[8px] border border-[var(--border-strong)] bg-[var(--bg-input)] px-3 py-2 text-[13.5px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-colors duration-150 focus:border-[var(--c-icon)] disabled:opacity-50",
      className
    )}
    {...props}
  />
));
TextareaBox.displayName = "TextareaBox";

export const SelectBox = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, ...props }, ref) => (
  <select
    ref={ref}
    className={cn(
      "w-full min-h-[38px] rounded-[8px] border border-[var(--border-strong)] bg-[var(--bg-input)] px-3 py-1.5 text-[13.5px] text-[var(--text-primary)] transition-colors duration-150 focus:border-[var(--c-icon)] disabled:opacity-50",
      className
    )}
    {...props}
  />
));
SelectBox.displayName = "SelectBox";

export function SwitchToggle({
  checked,
  onCheckedChange,
  disabled,
  id,
  "aria-label": ariaLabel,
}: {
  checked: boolean;
  onCheckedChange: (next: boolean) => void;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
}) {
  return (
    <RadixSwitch.Root
      id={id}
      aria-label={ariaLabel}
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      className="relative inline-flex h-[22px] w-[40px] shrink-0 cursor-pointer items-center rounded-full border border-[var(--border-strong)] bg-[var(--bg-elevated)] transition-colors duration-150 data-[state=checked]:bg-[var(--c-solid)] data-[state=checked]:border-transparent disabled:opacity-45 disabled:cursor-not-allowed"
    >
      <RadixSwitch.Thumb className="block h-[16px] w-[16px] translate-x-[2px] rounded-full bg-[var(--text-primary)] shadow transition-transform duration-150 data-[state=checked]:translate-x-[20px] data-[state=checked]:bg-[var(--c-on)]" />
    </RadixSwitch.Root>
  );
}
