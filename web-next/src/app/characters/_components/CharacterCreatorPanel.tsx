"use client";

import React, { useState } from "react";
import { Wand2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import type { CharacterRow } from "@/app/characters/types";
import { Card, SectionHeading } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  SwitchToggle,
  TextareaBox,
  TextInput,
} from "@/components/ui/form-controls";

export function CharacterCreatorPanel({
  workspaceId,
  characters,
  onReload,
  onMessage,
  onError,
}: {
  workspaceId: number;
  characters: CharacterRow[];
  onReload: () => Promise<void>;
  onMessage: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [charName, setCharName] = useState("");
  const [appearance, setAppearance] = useState("");
  const [seedInput, setSeedInput] = useState("778899");

  const [imgCharId, setImgCharId] = useState<number>(0);
  const [imgPrompt, setImgPrompt] = useState("");
  const [isProductShot, setIsProductShot] = useState(false);

  const createChar = async (e: React.FormEvent) => {
    e.preventDefault();
    onError("");
    onMessage("");
    try {
      await apiFetch("/api/v1/characters", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId,
          name: charName,
          appearance_prompt: appearance,
          seed: Number(seedInput) || undefined,
        }),
      });
      setCharName("");
      setAppearance("");
      onMessage("Đã tạo Nhân vật Cố định mới.");
      toast.success("Đã tạo nhân vật mới.");
      await onReload();
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Lỗi tạo nhân vật");
    }
  };

  const generateImg = async (e: React.FormEvent) => {
    e.preventDefault();
    onError("");
    onMessage("");
    try {
      await apiFetch("/api/v1/images", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId,
          character_id: imgCharId > 0 ? imgCharId : null,
          prompt: imgPrompt,
          is_product_shot: isProductShot,
          animate_to_shot: true,
        }),
      });
      setImgPrompt("");
      onMessage("Đã tạo khung cảnh + chuyển thành Shot chuyển động.");
      toast.success("Đã tạo ảnh & Shot chuyển động.");
      await onReload();
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Không thể sinh ảnh");
    }
  };

  const generateMuseVariants = async () => {
    onError("");
    onMessage("");
    try {
      await apiFetch("/api/v1/muse/tasks", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId,
          kind: "image",
          purpose: "character",
          prompt: imgPrompt || "Chân dung MC studio chuyên nghiệp ánh sáng mềm",
          count: 4,
          ref_type: imgCharId > 0 ? "character" : null,
          ref_id: imgCharId > 0 ? imgCharId : null,
          refs: imgCharId > 0 ? [{ type: "character", id: imgCharId }] : [],
        }),
      });
      void apiFetch("/api/v1/muse/dispatch", { method: "POST" }).catch(() => {});
      const m = "Đã xếp tạo 4 biến thể ảnh bằng Muse Gateway vào hàng chờ!";
      onMessage(m);
      toast.success(m);
      await onReload();
    } catch (e2) {
      onError(e2 instanceof Error ? e2.message : "Không thể tạo biến thể Muse");
    }
  };

  return (
    <div className="grid md:grid-cols-2 gap-4">
      <Card tinted>
        <form onSubmit={createChar} className="space-y-3.5">
          <SectionHeading>Tạo Nhân vật Đồng nhất</SectionHeading>
          <div>
            <FieldLabel htmlFor="chr-name">Tên nhân vật *</FieldLabel>
            <TextInput
              id="chr-name"
              required
              value={charName}
              onChange={(e) => setCharName(e.target.value)}
              placeholder="VD: MC Bảo Ngọc"
            />
          </div>
          <div>
            <FieldLabel htmlFor="chr-app">Mô tả ngoại hình cố định</FieldLabel>
            <TextareaBox
              id="chr-app"
              rows={2}
              value={appearance}
              onChange={(e) => setAppearance(e.target.value)}
              placeholder="Trang phục, kiểu tóc, phong thái..."
            />
          </div>
          <div>
            <FieldLabel htmlFor="chr-seed">Mã Seed cố định</FieldLabel>
            <TextInput
              id="chr-seed"
              type="number"
              value={seedInput}
              onChange={(e) => setSeedInput(e.target.value)}
              className="tabular-nums"
            />
          </div>
          <Button type="submit">Tạo Nhân Vật</Button>
        </form>
      </Card>

      <Card>
        <form onSubmit={generateImg} className="space-y-3.5">
          <SectionHeading>
            <Wand2 className="w-4 h-4 text-[var(--c-icon)]" /> Sinh Cảnh Nền &amp; Shot Chuyển Động
          </SectionHeading>
          <div>
            <FieldLabel htmlFor="img-chr">Gắn nhân vật</FieldLabel>
            <SelectBox
              id="img-chr"
              value={imgCharId}
              onChange={(e) => setImgCharId(Number(e.target.value))}
            >
              <option value={0}>Không gắn nhân vật</option>
              {characters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} (Seed {c.seed})
                </option>
              ))}
            </SelectBox>
          </div>
          <div>
            <FieldLabel htmlFor="img-prompt">Mô tả bối cảnh cảnh quay *</FieldLabel>
            <TextareaBox
              id="img-prompt"
              required
              rows={2}
              value={imgPrompt}
              onChange={(e) => setImgPrompt(e.target.value)}
              placeholder="VD: Bàn trưng bày ánh nắng sớm tối giản..."
            />
          </div>
          <div className="flex items-center gap-2.5">
            <SwitchToggle
              id="img-prd"
              checked={isProductShot}
              onCheckedChange={setIsProductShot}
            />
            <label
              htmlFor="img-prd"
              className="text-[12.5px] text-[var(--text-secondary)] cursor-pointer"
            >
              Cảnh có sản phẩm (chỉ cho phép ở Hybrid / Full AI)
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="secondary">
              Sinh Ảnh + Shot Chuyển Động
            </Button>
            <Button
              type="button"
              onClick={() => void generateMuseVariants()}
            >
              Tạo 4 biến thể bằng Muse
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
