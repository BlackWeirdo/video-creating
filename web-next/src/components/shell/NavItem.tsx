"use client";

import * as React from "react";
import Link from "next/link";
import { Star } from "lucide-react";
import { NavItemConfig } from "@/config/navigation";
import { NavCounts } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { HintTooltip } from "@/components/ui/overlays";
import { cn } from "@/lib/utils";

export function NavItemRow({
  item,
  active,
  collapsed,
  isPinned,
  alwaysShowPin = false,
  onTogglePin,
  navCounts,
}: {
  item: NavItemConfig;
  active: boolean;
  collapsed: boolean;
  isPinned?: boolean;
  alwaysShowPin?: boolean;
  onTogglePin?: (href: string) => void;
  navCounts: NavCounts | null;
}) {
  const Icon = item.icon;
  const cid = item.clusterId;

  let countText = "";
  let countTone: "emerald" | "amber" = "emerald";
  if (item.badgeType === "approvals" && (navCounts?.approvals_pending || 0) > 0) {
    countText = `${navCounts?.approvals_pending} chờ`;
    countTone = "emerald";
  } else if (item.badgeType === "suggestions" && (navCounts?.suggestions_new || 0) > 0) {
    countText = `${navCounts?.suggestions_new} mới`;
    countTone = "amber";
  }

  const hasFailedJob = Boolean(navCounts?.failed_routes?.includes(item.href));

  const itemVars = {
    "--item-icon": `var(--c-${cid}-icon)`,
    "--item-soft": `var(--c-${cid}-soft)`,
    "--item-bd": `var(--c-${cid}-bd)`,
    "--item-tx": `var(--c-${cid}-tx)`,
    "--item-glow": `var(--c-${cid}-glow)`,
  } as React.CSSProperties;

  const linkEl = (
    <Link
      href={item.href}
      style={itemVars}
      aria-current={active ? "page" : undefined}
      className={cn(
        "relative flex w-full min-h-[36px] items-center gap-2.5 rounded-[9px] border px-2.5 py-1.5 text-[13.5px] font-medium transition-all duration-150",
        collapsed && "justify-center px-2",
        !collapsed && onTogglePin && (alwaysShowPin ? "pr-8" : "group-hover:pr-8"),
        active
          ? "bg-[var(--item-soft)] border-[var(--item-bd)] text-[var(--item-tx)] font-semibold shadow-[var(--item-glow)]"
          : "border-transparent text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]"
      )}
    >
      {active && (
        <span
          aria-hidden="true"
          className="absolute -left-[1px] top-[7px] bottom-[7px] w-[3.5px] rounded-r bg-[var(--item-icon)]"
        />
      )}
      <Icon className="w-[17px] h-[17px] shrink-0 text-[var(--item-icon)]" />
      {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
      {!collapsed && countText && (
        <Badge tone={countTone} className="px-2 py-0 text-[11px] tabular-nums">
          {countText}
        </Badge>
      )}
      {!collapsed && hasFailedJob && (
        <span
          role="status"
          aria-label="Có tác vụ gặp lỗi trong 24 giờ qua"
          title="Có tác vụ gặp lỗi trong 24 giờ qua"
          className="h-2.5 w-2.5 shrink-0 rounded-full bg-rose-500 ring-3 ring-[var(--st-rose-bg)]"
        />
      )}
      {collapsed && (countText || hasFailedJob) && (
        <span
          aria-hidden="true"
          className={cn(
            "absolute right-1.5 top-1.5 h-2 w-2 rounded-full",
            hasFailedJob ? "bg-rose-500" : "bg-[var(--item-icon)]"
          )}
        />
      )}
    </Link>
  );

  return (
    <div className="group relative flex items-center">
      <HintTooltip
        enabled={collapsed}
        label={
          <span>
            {item.label}
            {countText ? ` (${countText})` : ""}
            {hasFailedJob ? " • Có tác vụ lỗi" : ""}
          </span>
        }
      >
        {linkEl}
      </HintTooltip>

      {!collapsed && onTogglePin && (
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onTogglePin(item.href);
          }}
          aria-label={isPinned ? `Bỏ ghim ${item.label}` : `Ghim ${item.label} lên đầu menu`}
          title={isPinned ? "Bỏ ghim khỏi mục yêu thích" : "Ghim vào mục yêu thích"}
          className={cn(
            "absolute right-1.5 h-[25px] w-[25px] items-center justify-center rounded-md bg-[var(--bg-card)]/90 text-[var(--text-muted)] hover:text-amber-400 cursor-pointer",
            alwaysShowPin ? "inline-flex" : "hidden group-hover:inline-flex",
            isPinned && "text-amber-400"
          )}
        >
          <Star className={cn("w-3.5 h-3.5", isPinned && "fill-current")} />
        </button>
      )}
    </div>
  );
}
