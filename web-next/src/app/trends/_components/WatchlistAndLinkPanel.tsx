"use client";

import React, { useState } from "react";
import { Link2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import type { SuggestionItem, WatchItem } from "@/app/trends/types";
import { SuggestionsList } from "@/app/trends/_components/SuggestionsList";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextInput } from "@/components/ui/form-controls";

export function WatchlistAndLinkPanel({
  workspaceId,
  watchlist,
  suggestions,
  onReload,
  onMessage,
  onError,
}: {
  workspaceId: number;
  watchlist: WatchItem[];
  suggestions: SuggestionItem[];
  onReload: () => Promise<void>;
  onMessage: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [source, setSource] = useState("youtube");
  const [kind, setKind] = useState("keyword");
  const [watchVal, setWatchVal] = useState("");
  const [pasteUrl, setPasteUrl] = useState("");

  const addWatch = async (e: React.FormEvent) => {
    e.preventDefault();
    onError("");
    onMessage("");
    try {
      await apiFetch("/api/v1/watchlist", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId,
          source,
          kind,
          value: watchVal,
        }),
      });
      setWatchVal("");
      onMessage("Đã thêm từ khóa / kênh theo dõi.");
      toast.success("Đã thêm vào danh sách theo dõi.");
      await onReload();
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Không thể thêm nguồn theo dõi");
    }
  };

  const deleteWatch = async (id: number) => {
    await apiFetch(`/api/v1/watchlist/${id}`, { method: "DELETE" });
    await onReload();
  };

  const submitLink = async (e: React.FormEvent) => {
    e.preventDefault();
    onError("");
    onMessage("");
    try {
      await apiFetch("/api/v1/trends/link", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspaceId, url: pasteUrl }),
      });
      setPasteUrl("");
      const m = "Đã nạp liên kết tham khảo & đưa vào hàng đợi phân tích cấu trúc.";
      onMessage(m);
      toast.success(m);
      await onReload();
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Không đọc được liên kết");
    }
  };

  const handleSuggestion = async (id: number, action: "accept" | "dismiss") => {
    await apiFetch(`/api/v1/suggestions/${id}/${action}`, {
      method: "POST",
      body:
        action === "accept"
          ? JSON.stringify({ workspace_id: workspaceId })
          : undefined,
    });
    const m =
      action === "accept"
        ? `Đã nhận đề xuất #${id} và khởi tạo kịch bản.`
        : `Đã bỏ qua đề xuất #${id}.`;
    onMessage(m);
    toast.success(m);
    await onReload();
  };

  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <Card tinted>
        <form onSubmit={addWatch} className="space-y-3.5">
          <SectionHeading>Theo dõi Kênh / Từ khóa tự động</SectionHeading>
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <FieldLabel htmlFor="tr-src">Nguồn nền tảng</FieldLabel>
              <SelectBox
                id="tr-src"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="youtube">YouTube Shorts</option>
                <option value="tiktok">TikTok</option>
                <option value="ig_hashtag">Instagram Hashtag</option>
                <option value="ig_discovery">Instagram Khám phá</option>
                <option value="facebook">Facebook Reels Page</option>
                <option value="ad_library">Thư viện Quảng cáo Meta</option>
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="tr-kind">Loại theo dõi</FieldLabel>
              <SelectBox
                id="tr-kind"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
              >
                <option value="keyword">Từ khóa</option>
                <option value="hashtag">Thẻ Hashtag</option>
                <option value="account">Tài khoản</option>
                <option value="page">Trang Fanpage</option>
              </SelectBox>
            </div>
          </div>

          <div className="flex gap-2 items-end">
            <div className="flex-1">
              <FieldLabel htmlFor="tr-val">Từ khóa hoặc địa chỉ kênh *</FieldLabel>
              <TextInput
                id="tr-val"
                required
                value={watchVal}
                onChange={(e) => setWatchVal(e.target.value)}
                placeholder="VD: dây chuyền bạc s925..."
              />
            </div>
            <Button type="submit" variant="secondary">
              <Plus className="w-4 h-4" /> Thêm
            </Button>
          </div>

          {watchlist.length > 0 && (
            <div className="space-y-1.5 max-h-44 overflow-y-auto pt-1">
              {watchlist.map((w) => (
                <div
                  key={w.id}
                  className="flex items-center justify-between gap-2 rounded-[9px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px]"
                >
                  <span className="truncate">
                    <Badge tone="cluster" className="mr-2 uppercase text-[11px]">
                      {w.source}
                    </Badge>
                    <span className="text-[var(--text-muted)]">{w.kind}: </span>
                    <strong className="text-[var(--text-primary)]">{w.value}</strong>
                  </span>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label={`Xóa theo dõi ${w.value}`}
                    onClick={() => void deleteWatch(w.id)}
                  >
                    <Trash2 className="w-4 h-4 text-rose-400" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </form>
      </Card>

      <Card className="space-y-4">
        <form onSubmit={submitLink} className="space-y-3">
          <SectionHeading>
            <Link2 className="w-4 h-4 text-[var(--c-icon)]" /> Dán Liên Kết Video Tham Khảo
          </SectionHeading>
          <p className="text-[12.5px] text-[var(--text-muted)]">
            Dán liên kết Reels hoặc Shorts công khai để hệ thống tự bóc tách cấu trúc giữ chân người xem.
          </p>
          <div className="flex gap-2 items-end">
            <div className="flex-1">
              <FieldLabel htmlFor="tr-url">Liên kết video công khai *</FieldLabel>
              <TextInput
                id="tr-url"
                required
                value={pasteUrl}
                onChange={(e) => setPasteUrl(e.target.value)}
                placeholder="https://www.facebook.com/reel/..."
              />
            </div>
            <Button type="submit">Nạp Liên Kết</Button>
          </div>
        </form>

        <SuggestionsList
          suggestions={suggestions}
          onAction={handleSuggestion}
        />
      </Card>
    </div>
  );
}
