"use client";

import React from "react";
import type { Workspace } from "@/lib/api/types";
import { Card, SectionHeading } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FieldLabel, SelectBox, TextInput } from "@/components/ui/form-controls";

export function StepWorkspaceSetup({
  wsMode,
  setWsMode,
  wsName,
  setWsName,
  wsNiche,
  setWsNiche,
  wsPolicy,
  setWsPolicy,
  wsRatio,
  setWsRatio,
  wsApproval,
  setWsApproval,
  onBack,
  onNext,
}: {
  wsMode: "update" | "create";
  setWsMode: (m: "update" | "create") => void;
  wsName: string;
  setWsName: (v: string) => void;
  wsNiche: string;
  setWsNiche: (v: string) => void;
  wsPolicy: Workspace["content_policy"];
  setWsPolicy: (v: Workspace["content_policy"]) => void;
  wsRatio: Workspace["default_aspect_ratio"];
  setWsRatio: (v: Workspace["default_aspect_ratio"]) => void;
  wsApproval: Workspace["approval_mode"];
  setWsApproval: (v: Workspace["approval_mode"]) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  return (
    <Card tinted className="space-y-4">
      <SectionHeading>
        Cấu hình Thương Hiệu Đầu Tiên &amp; Chính sách Nội dung
      </SectionHeading>
      <div className="flex flex-wrap gap-4 text-[13px]">
        <label className="inline-flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            checked={wsMode === "update"}
            onChange={() => setWsMode("update")}
            className="accent-[var(--c-solid)]"
          />
          <span>Cập nhật Workspace hiện tại</span>
        </label>
        <label className="inline-flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            checked={wsMode === "create"}
            onChange={() => {
              setWsMode("create");
              setWsName("");
            }}
            className="accent-[var(--c-solid)]"
          />
          <span>Tạo mới một Workspace riêng</span>
        </label>
      </div>

      <div className="grid md:grid-cols-2 gap-3.5">
        <div>
          <FieldLabel htmlFor="wz-name">Tên thương hiệu / Dự án</FieldLabel>
          <TextInput
            id="wz-name"
            value={wsName}
            onChange={(e) => setWsName(e.target.value)}
            placeholder="VD: Trang Sức Bạc S925"
          />
        </div>
        <div>
          <FieldLabel htmlFor="wz-niche">Ngành hàng / Chủ đề</FieldLabel>
          <TextInput
            id="wz-niche"
            value={wsNiche}
            onChange={(e) => setWsNiche(e.target.value)}
          />
        </div>
        <div>
          <FieldLabel htmlFor="wz-policy">Chính sách Nội dung</FieldLabel>
          <SelectBox
            id="wz-policy"
            value={wsPolicy}
            onChange={(e) =>
              setWsPolicy(e.target.value as Workspace["content_policy"])
            }
          >
            <option value="strict_footage">
              Strict Footage (100% cảnh quay sản phẩm thật)
            </option>
            <option value="hybrid_remix">
              Hybrid Remix (Việt hóa + chèn cảnh quay thật)
            </option>
            <option value="full_ai">
              Full AI (Truyện, Bản tin, Podcast, Việt hóa)
            </option>
          </SelectBox>
        </div>
        <div>
          <FieldLabel htmlFor="wz-ratio">
            Tỷ lệ khung hình &amp; Chế độ duyệt
          </FieldLabel>
          <div className="grid grid-cols-2 gap-2">
            <SelectBox
              id="wz-ratio"
              value={wsRatio}
              onChange={(e) =>
                setWsRatio(e.target.value as Workspace["default_aspect_ratio"])
              }
            >
              <option value="9:16">9:16 Dọc</option>
              <option value="16:9">16:9 Ngang</option>
              <option value="1:1">1:1 Vuông</option>
            </SelectBox>
            <SelectBox
              aria-label="Chế độ duyệt mặc định"
              value={wsApproval}
              onChange={(e) =>
                setWsApproval(e.target.value as Workspace["approval_mode"])
              }
            >
              <option value="single">Duyệt từng bài</option>
              <option value="bulk">Duyệt hàng loạt</option>
              <option value="autopilot">Tự động đăng</option>
            </SelectBox>
          </div>
        </div>
      </div>

      <div className="flex justify-between">
        <Button type="button" variant="secondary" onClick={onBack}>
          ← Quay lại
        </Button>
        <Button type="button" onClick={onNext}>
          Tiếp tục: Khóa AI →
        </Button>
      </div>
    </Card>
  );
}
