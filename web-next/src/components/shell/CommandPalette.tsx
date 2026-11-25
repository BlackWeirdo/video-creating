"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { Command } from "cmdk";
import * as RadixDialog from "@radix-ui/react-dialog";
import {
  Moon,
  Monitor,
  Pause,
  Play,
  Plus,
  Search,
  Sun,
  Terminal,
} from "lucide-react";
import {
  ALL_NAV_ITEMS,
  NAV_CLUSTERS,
  OVERVIEW_NAV_ITEM,
  SETTINGS_NAV_ITEM,
  WELCOME_NAV_ITEM,
} from "@/config/navigation";
import { normalizeVi } from "@/lib/utils";

export function CommandPalette({
  open,
  onOpenChange,
  queuePaused,
  onTogglePause,
  onToggleLogs,
  onOpenCreateWs,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  queuePaused: boolean;
  onTogglePause: () => void;
  onToggleLogs: () => void;
  onOpenCreateWs: () => void;
}) {
  const router = useRouter();
  const { setTheme } = useTheme();

  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  const runAndClose = (fn: () => void) => {
    fn();
    onOpenChange(false);
  };

  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-50 bg-[var(--bg-scrim)] backdrop-blur-xs" />
        <RadixDialog.Content
          aria-label="Tìm nhanh chức năng"
          className="fixed left-1/2 top-[12%] z-50 w-[calc(100%-2rem)] max-w-[540px] -translate-x-1/2 overflow-hidden rounded-[16px] border border-[var(--border-strong)] bg-[var(--bg-card)] shadow-[var(--shadow-xl)] focus:outline-none"
        >
          <RadixDialog.Title className="sr-only">
            Bảng lệnh tìm nhanh chức năng
          </RadixDialog.Title>
          <Command
            filter={(value, search) =>
              normalizeVi(value).includes(normalizeVi(search)) ? 1 : 0
            }
            className="flex flex-col"
          >
            <div className="flex items-center gap-2.5 border-b border-[var(--border-subtle)] px-4 py-3">
              <Search className="w-4 h-4 text-[var(--c-icon)] shrink-0" />
              <Command.Input
                autoFocus
                placeholder="Gõ tên chức năng không dấu (vd: viet hoa, duyet, freecut, cai dat)..."
                className="flex-1 bg-transparent text-[14px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none"
              />
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                className="rounded border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-2 py-0.5 font-mono text-[11px] text-[var(--text-secondary)] cursor-pointer"
              >
                Esc
              </button>
            </div>

            <Command.List className="max-h-[360px] overflow-y-auto p-2 space-y-2">
              <Command.Empty className="py-8 text-center text-[13px] text-[var(--text-muted)]">
                Không tìm thấy trang hoặc thao tác phù hợp.
              </Command.Empty>

              <Command.Group
                heading="Đi tới nhanh"
                className="text-[11.5px] font-semibold text-[var(--text-muted)] px-1.5"
              >
                {[OVERVIEW_NAV_ITEM, SETTINGS_NAV_ITEM, WELCOME_NAV_ITEM].map(
                  (it) => {
                    const Icon = it.icon;
                    return (
                      <Command.Item
                        key={it.href}
                        value={`${it.label} ${it.keywords}`}
                        onSelect={() => runAndClose(() => router.push(it.href))}
                        className="flex items-center justify-between gap-2 rounded-[9px] px-2.5 py-2 text-[13.5px] font-medium text-[var(--text-primary)] cursor-pointer data-[selected=true]:bg-[var(--c-soft)] data-[selected=true]:text-[var(--c-tx)]"
                      >
                        <span className="inline-flex items-center gap-2.5">
                          <Icon className="w-4 h-4 text-[var(--c-icon)]" />
                          <span>{it.label}</span>
                        </span>
                        <span className="text-[11.5px] text-[var(--text-muted)]">
                          {it.clusterLabel}
                        </span>
                      </Command.Item>
                    );
                  }
                )}
              </Command.Group>

              {NAV_CLUSTERS.map((cluster) => (
                <Command.Group
                  key={cluster.id}
                  heading={cluster.label}
                  className="text-[11.5px] font-semibold text-[var(--text-muted)] px-1.5"
                >
                  {cluster.items.map((it) => {
                    const Icon = it.icon;
                    return (
                      <Command.Item
                        key={it.href}
                        value={`${it.label} ${cluster.label} ${it.keywords}`}
                        onSelect={() => runAndClose(() => router.push(it.href))}
                        className="flex items-center justify-between gap-2 rounded-[9px] px-2.5 py-2 text-[13.5px] font-medium text-[var(--text-primary)] cursor-pointer data-[selected=true]:bg-[var(--c-soft)] data-[selected=true]:text-[var(--c-tx)]"
                      >
                        <span className="inline-flex items-center gap-2.5">
                          <Icon
                            className="w-4 h-4"
                            style={{ color: `var(--c-${cluster.id}-icon)` }}
                          />
                          <span>{it.label}</span>
                        </span>
                        <span className="text-[11.5px] text-[var(--text-muted)]">
                          {cluster.label}
                        </span>
                      </Command.Item>
                    );
                  })}
                </Command.Group>
              ))}

              <Command.Group
                heading="Thao tác nhanh"
                className="text-[11.5px] font-semibold text-[var(--text-muted)] px-1.5"
              >
                <Command.Item
                  value="Chuyển sang giao diện Sáng light mode theme"
                  onSelect={() => runAndClose(() => setTheme("light"))}
                  className="flex items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-[13.5px] font-medium text-[var(--text-primary)] cursor-pointer data-[selected=true]:bg-[var(--c-soft)] data-[selected=true]:text-[var(--c-tx)]"
                >
                  <Sun className="w-4 h-4 text-amber-400" /> Chuyển sang giao diện Sáng
                </Command.Item>
                <Command.Item
                  value="Chuyển sang giao diện Tối dark mode theme"
                  onSelect={() => runAndClose(() => setTheme("dark"))}
                  className="flex items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-[13.5px] font-medium text-[var(--text-primary)] cursor-pointer data-[selected=true]:bg-[var(--c-soft)] data-[selected=true]:text-[var(--c-tx)]"
                >
                  <Moon className="w-4 h-4 text-sky-400" /> Chuyển sang giao diện Tối
                </Command.Item>
                <Command.Item
                  value="Theo giao diện Windows system theme"
                  onSelect={() => runAndClose(() => setTheme("system"))}
                  className="flex items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-[13.5px] font-medium text-[var(--text-primary)] cursor-pointer data-[selected=true]:bg-[var(--c-soft)] data-[selected=true]:text-[var(--c-tx)]"
                >
                  <Monitor className="w-4 h-4 text-[var(--text-muted)]" /> Tự động Sáng / Tối theo Windows
                </Command.Item>
                <Command.Item
                  value="Tạo Workspace thương hiệu mới create brand"
                  onSelect={() => runAndClose(onOpenCreateWs)}
                  className="flex items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-[13.5px] font-medium text-[var(--text-primary)] cursor-pointer data-[selected=true]:bg-[var(--c-soft)] data-[selected=true]:text-[var(--c-tx)]"
                >
                  <Plus className="w-4 h-4 text-[var(--c-icon)]" /> Tạo Workspace mới
                </Command.Item>
                <Command.Item
                  value="Tạm dừng chạy tiếp hàng đợi queue pause resume"
                  onSelect={() => runAndClose(onTogglePause)}
                  className="flex items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-[13.5px] font-medium text-[var(--text-primary)] cursor-pointer data-[selected=true]:bg-[var(--c-soft)] data-[selected=true]:text-[var(--c-tx)]"
                >
                  {queuePaused ? (
                    <Play className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <Pause className="w-4 h-4 text-amber-400" />
                  )}
                  {queuePaused ? "Chạy tiếp hàng đợi" : "Tạm dừng hàng đợi"}
                </Command.Item>
                <Command.Item
                  value="Mở đóng nhật ký hệ thống logs terminal"
                  onSelect={() => runAndClose(onToggleLogs)}
                  className="flex items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-[13.5px] font-medium text-[var(--text-primary)] cursor-pointer data-[selected=true]:bg-[var(--c-soft)] data-[selected=true]:text-[var(--c-tx)]"
                >
                  <Terminal className="w-4 h-4 text-[var(--text-muted)]" /> Bật / Ẩn Nhật ký hệ thống
                </Command.Item>
              </Command.Group>
            </Command.List>
          </Command>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

export { ALL_NAV_ITEMS };
