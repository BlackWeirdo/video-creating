"use client";

import * as React from "react";
import * as RadixDialog from "@radix-ui/react-dialog";
import * as RadixDropdown from "@radix-ui/react-dropdown-menu";
import * as RadixTabs from "@radix-ui/react-tabs";
import * as RadixCollapsible from "@radix-ui/react-collapsible";
import * as RadixTooltip from "@radix-ui/react-tooltip";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export function ModalDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  maxWidthClass = "max-w-lg",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  maxWidthClass?: string;
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-50 bg-[var(--bg-scrim)] backdrop-blur-xs" />
        <RadixDialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-[16px] border border-[var(--border-strong)] bg-[var(--bg-card)] p-5 shadow-[var(--shadow-xl)] focus:outline-none",
            maxWidthClass
          )}
        >
          <div className="flex items-start justify-between gap-3 mb-3">
            <div>
              <RadixDialog.Title className="text-[16px] font-bold text-[var(--text-primary)]">
                {title}
              </RadixDialog.Title>
              {description && (
                <RadixDialog.Description className="text-[13px] text-[var(--text-muted)] mt-1">
                  {description}
                </RadixDialog.Description>
              )}
            </div>
            <RadixDialog.Close
              aria-label="Đóng hộp thoại"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-transparent text-[var(--text-muted)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)] cursor-pointer"
            >
              <X className="w-4 h-4" />
            </RadixDialog.Close>
          </div>
          {children}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

export const DropdownRoot = RadixDropdown.Root;
export const DropdownTrigger = RadixDropdown.Trigger;
export function DropdownPanel({
  className,
  children,
  align = "start",
  sideOffset = 6,
}: {
  className?: string;
  children: React.ReactNode;
  align?: "start" | "center" | "end";
  sideOffset?: number;
}) {
  return (
    <RadixDropdown.Portal>
      <RadixDropdown.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(
          "z-50 min-w-[230px] rounded-[12px] border border-[var(--border-strong)] bg-[var(--bg-card)] p-1.5 shadow-[var(--shadow-xl)]",
          className
        )}
      >
        {children}
      </RadixDropdown.Content>
    </RadixDropdown.Portal>
  );
}
export const DropdownItem = RadixDropdown.Item;
export const DropdownSeparator = RadixDropdown.Separator;

export const TabsRoot = RadixTabs.Root;
export function TabsBar({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof RadixTabs.List>) {
  return (
    <RadixTabs.List
      className={cn(
        "inline-flex flex-wrap items-center gap-1 rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-1",
        className
      )}
      {...props}
    />
  );
}
export function TabTrigger({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof RadixTabs.Trigger>) {
  return (
    <RadixTabs.Trigger
      className={cn(
        "inline-flex min-h-[34px] items-center gap-2 rounded-[8px] px-3.5 py-1.5 text-[13px] font-medium text-[var(--text-muted)] cursor-pointer transition-colors duration-150 hover:text-[var(--text-primary)] data-[state=active]:bg-[var(--bg-card)] data-[state=active]:text-[var(--c-tx)] data-[state=active]:font-semibold data-[state=active]:shadow-[var(--shadow-sm)]",
        className
      )}
      {...props}
    />
  );
}
export const TabPanel = RadixTabs.Content;

export const CollapsibleRoot = RadixCollapsible.Root;
export const CollapsibleTrigger = RadixCollapsible.Trigger;
export const CollapsibleContent = RadixCollapsible.Content;

export const TooltipProvider = RadixTooltip.Provider;
export function HintTooltip({
  label,
  side = "right",
  enabled = true,
  children,
}: {
  label: React.ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  enabled?: boolean;
  children: React.ReactNode;
}) {
  if (!enabled) return <>{children}</>;
  return (
    <RadixTooltip.Root delayDuration={180}>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={8}
          className="z-50 rounded-[8px] border border-[var(--border-strong)] bg-[var(--bg-card)] px-2.5 py-1.5 text-[12px] font-medium text-[var(--text-primary)] shadow-[var(--shadow-md)]"
        >
          {label}
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}
