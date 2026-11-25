import * as React from "react";
import { ShieldCheck } from "lucide-react";
import { Badge, PillTone } from "@/components/ui/badge";
import { Workspace } from "@/lib/api";

const POLICY_META: Record<
  Workspace["content_policy"],
  { label: string; detail: string; tone: PillTone }
> = {
  strict_footage: {
    label: "Strict Footage",
    detail: "Chỉ dùng Shot quay thật",
    tone: "emerald",
  },
  hybrid_remix: {
    label: "Hybrid Remix",
    detail: "Cho phép tráo Shot thật",
    tone: "amber",
  },
  full_ai: {
    label: "Full AI",
    detail: "Mở trọn bộ AI & Việt hóa",
    tone: "sky",
  },
};

export function PolicyBadge({
  policy,
  showDetail = false,
}: {
  policy?: Workspace["content_policy"] | null;
  showDetail?: boolean;
}) {
  const meta = POLICY_META[policy || "strict_footage"] || POLICY_META.strict_footage;
  return (
    <Badge tone={meta.tone}>
      <ShieldCheck className="w-3.5 h-3.5 shrink-0" />
      <span>{showDetail ? `${meta.label} • ${meta.detail}` : meta.label}</span>
    </Badge>
  );
}
