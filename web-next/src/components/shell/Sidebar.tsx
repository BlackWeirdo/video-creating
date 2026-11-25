"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import {
  ChevronDown,
  Layers,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Star,
} from "lucide-react";
import {
  ALL_NAV_ITEMS,
  ClusterId,
  isRouteActive,
  NAV_CLUSTERS,
  OVERVIEW_NAV_ITEM,
  SETTINGS_NAV_ITEM,
  STORAGE_KEYS,
  WELCOME_NAV_ITEM,
} from "@/config/navigation";
import { NavCounts } from "@/lib/api";
import {
  CollapsibleContent,
  CollapsibleRoot,
  CollapsibleTrigger,
  HintTooltip,
} from "@/components/ui/overlays";
import { NavItemRow } from "@/components/shell/NavItem";
import { WorkspaceSwitcher } from "@/components/shell/WorkspaceSwitcher";
import { cn } from "@/lib/utils";

const DEFAULT_FAVS = ["/localize", "/approval"];
const DEFAULT_OPEN: Record<ClusterId, boolean> = {
  source: true,
  produce: false,
  adapt: true,
  edit: false,
  publish: true,
};

export function Sidebar({
  collapsed,
  onToggleCollapse,
  onOpenCmdk,
  onOpenCreateWs,
  wizardNeeded,
  navCounts,
  museRunning = 0,
}: {
  collapsed: boolean;
  onToggleCollapse: () => void;
  onOpenCmdk: () => void;
  onOpenCreateWs: () => void;
  wizardNeeded: boolean;
  navCounts: NavCounts | null;
  museRunning?: number;
}) {
  const pathname = usePathname();
  const [openMap, setOpenMap] = React.useState<Record<ClusterId, boolean>>(DEFAULT_OPEN);
  const [favorites, setFavorites] = React.useState<string[]>(DEFAULT_FAVS);

  const loadStoredPrefs = React.useCallback(() => {
    try {
      const rawClusters = localStorage.getItem(STORAGE_KEYS.CLUSTERS);
      if (rawClusters) {
        setOpenMap((prev) => ({ ...prev, ...JSON.parse(rawClusters) }));
      }
      const rawFavs = localStorage.getItem(STORAGE_KEYS.FAVORITES);
      if (rawFavs) {
        const parsed = JSON.parse(rawFavs);
        if (Array.isArray(parsed)) setFavorites(parsed);
      }
    } catch {
      // ignore corrupted storage
    }
  }, []);

  React.useEffect(() => {
    loadStoredPrefs();
    window.addEventListener("vc:nav-prefs-changed", loadStoredPrefs);
    return () => window.removeEventListener("vc:nav-prefs-changed", loadStoredPrefs);
  }, [loadStoredPrefs]);

  // Auto-open the cluster containing the current active page
  React.useEffect(() => {
    for (const cluster of NAV_CLUSTERS) {
      if (cluster.items.some((it) => isRouteActive(pathname, it.href))) {
        setOpenMap((prev) => {
          if (prev[cluster.id]) return prev;
          const next = { ...prev, [cluster.id]: true };
          try {
            localStorage.setItem(STORAGE_KEYS.CLUSTERS, JSON.stringify(next));
          } catch {
            // ignore
          }
          return next;
        });
        break;
      }
    }
  }, [pathname]);

  const setClusterOpen = (cid: ClusterId, nextOpen: boolean) => {
    setOpenMap((prev) => {
      const next = { ...prev, [cid]: nextOpen };
      try {
        localStorage.setItem(STORAGE_KEYS.CLUSTERS, JSON.stringify(next));
      } catch {
        // ignore
      }
      return next;
    });
  };

  const toggleFavorite = (href: string) => {
    setFavorites((prev) => {
      const next = prev.includes(href)
        ? prev.filter((x) => x !== href)
        : prev.length < 5
          ? [...prev, href]
          : prev;
      try {
        localStorage.setItem(STORAGE_KEYS.FAVORITES, JSON.stringify(next));
      } catch {
        // ignore
      }
      return next;
    });
  };

  const favConfigs = favorites
    .map((href) => ALL_NAV_ITEMS.find((it) => it.href === href))
    .filter((it): it is NonNullable<typeof it> => Boolean(it));

  return (
    <aside
      aria-label="Điều hướng Studio"
      style={{
        background:
          "linear-gradient(180deg, var(--c-soft) 0%, transparent 240px), var(--bg-sidebar)",
      }}
      className={cn(
        "sticky top-0 z-30 flex h-screen shrink-0 flex-col border-r border-[var(--border-subtle)] transition-[width] duration-200 ease-out",
        collapsed ? "w-[68px]" : "w-[276px]"
      )}
    >
      {/* Brand + Collapse Rail Button */}
      <div
        className={cn(
          "flex items-center border-b border-[var(--border-subtle)] px-3.5 py-3",
          collapsed ? "justify-center px-2" : "justify-between gap-2"
        )}
      >
        {!collapsed && (
          <div className="flex items-center gap-2.5 min-w-0">
            <div
              aria-hidden="true"
              style={{ background: "var(--c-grad)" }}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] border border-[var(--c-bd)] text-[var(--c-icon)] shadow-[var(--c-glow)]"
            >
              <Layers className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <div className="truncate text-[14.5px] font-bold tracking-tight text-[var(--text-primary)]">
                Video Creator V2
              </div>
              <div className="truncate text-[11.5px] text-[var(--text-muted)]">
                Studio Video Đa Kênh AI
              </div>
            </div>
          </div>
        )}

        <HintTooltip
          enabled
          side={collapsed ? "right" : "bottom"}
          label={collapsed ? "Mở rộng thanh bên" : "Thu gọn thanh bên thành dải icon"}
        >
          <button
            type="button"
            onClick={onToggleCollapse}
            aria-label={collapsed ? "Mở rộng thanh bên" : "Thu gọn thanh bên"}
            className="inline-flex h-[34px] w-[34px] items-center justify-center rounded-[8px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:border-[var(--c-bd)] hover:text-[var(--text-primary)] cursor-pointer transition-colors"
          >
            {collapsed ? (
              <PanelLeftOpen className="w-4 h-4" />
            ) : (
              <PanelLeftClose className="w-4 h-4" />
            )}
          </button>
        </HintTooltip>
      </div>

      {/* Workspace Card + Ctrl+K Search */}
      <div className="border-b border-[var(--border-subtle)] p-3 space-y-2">
        <WorkspaceSwitcher collapsed={collapsed} onOpenCreate={onOpenCreateWs} />

        <HintTooltip enabled={collapsed} label="Tìm nhanh chức năng (Ctrl+K)">
          <button
            type="button"
            onClick={onOpenCmdk}
            aria-label="Tìm nhanh chức năng (Ctrl+K)"
            className={cn(
              "flex w-full min-h-[36px] items-center rounded-[9px] border border-[var(--border-subtle)] bg-[var(--bg-input)] text-[13px] text-[var(--text-muted)] hover:border-[var(--c-bd)] hover:text-[var(--text-primary)] cursor-pointer transition-colors",
              collapsed ? "justify-center px-2" : "justify-between px-2.5 py-1.5 gap-2"
            )}
          >
            <span className="inline-flex items-center gap-2">
              <Search className="w-4 h-4 shrink-0" />
              {!collapsed && <span>Tìm nhanh chức năng...</span>}
            </span>
            {!collapsed && (
              <kbd className="rounded border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-secondary)]">
                Ctrl K
              </kbd>
            )}
          </button>
        </HintTooltip>
      </div>

      {/* Clustered Navigation */}
      <nav
        aria-label="Danh mục chức năng chính"
        className="flex-1 overflow-y-auto px-2.5 py-2.5 space-y-2.5"
      >
        <NavItemRow
          item={OVERVIEW_NAV_ITEM}
          active={isRouteActive(pathname, "/")}
          collapsed={collapsed}
          navCounts={navCounts}
        />

        {favConfigs.length > 0 && !collapsed && (
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 px-2 py-1 text-[11.5px] font-bold text-[var(--text-muted)]">
              <Star className="w-3.5 h-3.5 text-amber-400 fill-amber-400" />
              <span>Đã ghim nhanh ({favConfigs.length})</span>
            </div>
            <div className="space-y-0.5 pl-1">
              {favConfigs.map((it) => (
                <NavItemRow
                  key={`fav-${it.href}`}
                  item={it}
                  active={isRouteActive(pathname, it.href)}
                  collapsed={false}
                  isPinned
                  alwaysShowPin
                  onTogglePin={toggleFavorite}
                  navCounts={navCounts}
                />
              ))}
            </div>
          </div>
        )}

        {NAV_CLUSTERS.map((cluster) => {
          const isOpen = collapsed ? true : openMap[cluster.id] !== false;
          return (
            <CollapsibleRoot
              key={cluster.id}
              open={isOpen}
              onOpenChange={(next) => {
                if (!collapsed) setClusterOpen(cluster.id, next);
              }}
              className="space-y-0.5"
            >
              {collapsed ? (
                <div
                  title={cluster.label}
                  className="flex justify-center py-1.5"
                >
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: `var(--c-${cluster.id}-icon)` }}
                  />
                </div>
              ) : (
                <CollapsibleTrigger asChild>
                  <button
                    type="button"
                    className="flex w-full min-h-[31px] items-center justify-between gap-2 rounded-[8px] px-2 py-1 text-[12px] font-bold tracking-wide text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)] cursor-pointer transition-colors"
                  >
                    <span className="inline-flex items-center gap-2">
                      <span
                        className="h-2 w-2 rounded-full shrink-0"
                        style={{ backgroundColor: `var(--c-${cluster.id}-icon)` }}
                      />
                      <span>{cluster.label}</span>
                    </span>
                    <ChevronDown
                      className={cn(
                        "w-3.5 h-3.5 text-[var(--text-muted)] transition-transform duration-200",
                        !isOpen && "-rotate-90"
                      )}
                    />
                  </button>
                </CollapsibleTrigger>
              )}

              <CollapsibleContent
                className={cn("space-y-0.5", !collapsed && "pl-1")}
              >
                {cluster.items.map((it) => (
                  <NavItemRow
                    key={it.href}
                    item={it}
                    active={isRouteActive(pathname, it.href)}
                    collapsed={collapsed}
                    isPinned={favorites.includes(it.href)}
                    onTogglePin={toggleFavorite}
                    navCounts={navCounts}
                    museRunning={museRunning}
                  />
                ))}
              </CollapsibleContent>
            </CollapsibleRoot>
          );
        })}
      </nav>

      {/* Pinned Footer */}
      <div className="border-t border-[var(--border-subtle)] px-2.5 py-2 space-y-0.5">
        {wizardNeeded && (
          <NavItemRow
            item={WELCOME_NAV_ITEM}
            active={isRouteActive(pathname, WELCOME_NAV_ITEM.href)}
            collapsed={collapsed}
            navCounts={navCounts}
          />
        )}
        <NavItemRow
          item={SETTINGS_NAV_ITEM}
          active={isRouteActive(pathname, SETTINGS_NAV_ITEM.href)}
          collapsed={collapsed}
          navCounts={navCounts}
        />
      </div>
    </aside>
  );
}
