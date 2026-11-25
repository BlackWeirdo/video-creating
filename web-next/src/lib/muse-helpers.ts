import type { PillTone } from "@/components/ui/badge";

export interface MuseStatusLabel {
  label: string;
  tone: PillTone;
}

export function formatMuseTaskStatus(status: string, partial = false): MuseStatusLabel {
  switch (status) {
    case "pending":
      return { label: "Chờ điều phối", tone: "neutral" };
    case "submitted":
      return { label: "Đang render Muse", tone: "cluster" };
    case "importing":
      return { label: "Đang tải về kho", tone: "sky" };
    case "succeeded":
      return partial
        ? { label: "Hoàn tất (dừng sớm)", tone: "amber" }
        : { label: "Hoàn tất", tone: "emerald" };
    case "waiting_quota":
      return { label: "Chờ hồi hạn mức", tone: "amber" };
    case "cancelled":
      return { label: "Đã hủy", tone: "neutral" };
    case "failed":
      return { label: "Thất bại", tone: "rose" };
    default:
      return { label: status || "Không rõ", tone: "neutral" };
  }
}

export function estimateParallelCapacity(
  readyOrBusyAccounts: number,
  rendersPerAccount = 2,
  maxParallel = 8
): number {
  const accs = Math.max(0, Math.trunc(readyOrBusyAccounts));
  const perAcc = Math.max(1, Math.trunc(rendersPerAccount));
  const cap = Math.max(1, Math.trunc(maxParallel));
  return Math.min(cap, accs * perAcc);
}

export function mapMuseErrorToVi(rawError: string | null | undefined): string {
  const txt = (rawError || "").trim();
  if (!txt) return "";
  const lower = txt.toLowerCase();
  if (lower.includes("cmdmode") || lower.includes("hardened") || lower.includes("rce")) {
    return "Gateway chưa vá bảo mật (vc-hardened / cmdMode=off) — hệ thống đã tự động chặn kết nối.";
  }
  if (lower.includes("401") || lower.includes("403") || lower.includes("xác thực")) {
    return "Khóa API Muse Gateway hết hiệu lực hoặc thiếu quyền — hãy bấm 'Kết nối 1 chạm' lại.";
  }
  if (lower.includes("quota") || lower.includes("cooldown") || lower.includes("429")) {
    return "Tài khoản Muse đang nghỉ hồi hạn mức — tác vụ sẽ tự chạy tiếp khi hết cooldown.";
  }
  if (lower.includes("restarted")) {
    return "Muse Gateway vừa khởi động lại khi đang render — hệ thống tự động xếp lịch thử lại.";
  }
  return txt;
}
