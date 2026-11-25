import {
  BookOpen,
  Bot,
  CheckCircle2,
  Clapperboard,
  Film,
  Flame,
  FolderKanban,
  Languages,
  Layers,
  LayoutDashboard,
  LucideIcon,
  Mic,
  Newspaper,
  Palette,
  Rocket,
  Scissors,
  Settings,
  Sparkles,
  UserCheck,
  Workflow,
} from "lucide-react";

export type ClusterId = "source" | "produce" | "adapt" | "edit" | "publish";

export interface NavItemConfig {
  href: string;
  label: string;
  icon: LucideIcon;
  clusterId: ClusterId;
  clusterLabel: string;
  keywords: string;
  badgeType?: "approvals" | "suggestions";
}

export interface NavClusterConfig {
  id: ClusterId;
  label: string;
  items: NavItemConfig[];
}

export const STORAGE_KEYS = {
  CLUSTERS: "vc.nav.clusters",
  FAVORITES: "vc.nav.favorites",
  SIDEBAR_COLLAPSED: "vc.nav.collapsed",
} as const;

export const OVERVIEW_NAV_ITEM: NavItemConfig = {
  href: "/",
  label: "Tổng quan",
  icon: LayoutDashboard,
  clusterId: "produce",
  clusterLabel: "Tổng quan",
  keywords: "tong quan dashboard trang chu kpi",
};

export const SETTINGS_NAV_ITEM: NavItemConfig = {
  href: "/settings",
  label: "Cài đặt & Mô hình AI",
  icon: Settings,
  clusterId: "adapt",
  clusterLabel: "Hệ thống",
  keywords: "cai dat settings api key model sao luu vcx giao dien",
};

export const WELCOME_NAV_ITEM: NavItemConfig = {
  href: "/welcome",
  label: "Hướng dẫn thiết lập",
  icon: Rocket,
  clusterId: "produce",
  clusterLabel: "Thiết lập ban đầu",
  keywords: "welcome wizard huong dan thiet lap ban dau",
};

export const NAV_CLUSTERS: NavClusterConfig[] = [
  {
    id: "source",
    label: "Nguồn & Tài nguyên",
    items: [
      {
        href: "/trends",
        label: "Xu hướng & Công thức",
        icon: Flame,
        clusterId: "source",
        clusterLabel: "Nguồn & Tài nguyên",
        keywords: "xu huong trend cong thuc tiktok douyin goi y",
        badgeType: "suggestions",
      },
      {
        href: "/products",
        label: "Sản phẩm & Dữ kiện",
        icon: FolderKanban,
        clusterId: "source",
        clusterLabel: "Nguồn & Tài nguyên",
        keywords: "san pham product du kien usp gia ban",
      },
      {
        href: "/footage",
        label: "Kho Footage & Shot",
        icon: Film,
        clusterId: "source",
        clusterLabel: "Nguồn & Tài nguyên",
        keywords: "kho footage shot canh quay video goc",
      },
      {
        href: "/characters",
        label: "Nhân vật & Ảnh AI",
        icon: UserCheck,
        clusterId: "source",
        clusterLabel: "Nguồn & Tài nguyên",
        keywords: "nhan vat anh ai avatar tach nen rembg",
      },
    ],
  },
  {
    id: "produce",
    label: "Sản xuất video",
    items: [
      {
        href: "/videos",
        label: "Kịch bản & Sản xuất",
        icon: Clapperboard,
        clusterId: "produce",
        clusterLabel: "Sản xuất video",
        keywords: "kich ban san xuat video tao moi render",
      },
      {
        href: "/batch",
        label: "Sản xuất hàng loạt (A/B)",
        icon: Layers,
        clusterId: "produce",
        clusterLabel: "Sản xuất video",
        keywords: "san xuat hang loat batch ab test",
      },
      {
        href: "/workflows",
        label: "Quy trình tự động (Workflow)",
        icon: Workflow,
        clusterId: "produce",
        clusterLabel: "Sản xuất video",
        keywords: "quy trinh tu dong workflow node dag",
      },
    ],
  },
  {
    id: "adapt",
    label: "Studio chuyển thể",
    items: [
      {
        href: "/localize",
        label: "Việt hóa & Remix",
        icon: Languages,
        clusterId: "adapt",
        clusterLabel: "Studio chuyển thể",
        keywords: "viet hoa remix reup douyin dich long tieng vieneu",
      },
      {
        href: "/news",
        label: "Tin tức → Video",
        icon: Newspaper,
        clusterId: "adapt",
        clusterLabel: "Studio chuyển thể",
        keywords: "tin tuc news bao chi diem tin",
      },
      {
        href: "/novel",
        label: "Truyện → Video",
        icon: BookOpen,
        clusterId: "adapt",
        clusterLabel: "Studio chuyển thể",
        keywords: "truyen tieu thuyet novel ke chuyen",
      },
      {
        href: "/podcast",
        label: "Podcast Sóng nhạc",
        icon: Mic,
        clusterId: "adapt",
        clusterLabel: "Studio chuyển thể",
        keywords: "podcast song nhac doi thoai mc",
      },
    ],
  },
  {
    id: "edit",
    label: "Dựng & Phong cách",
    items: [
      {
        href: "/editor",
        label: "Trình dựng (FreeCut)",
        icon: Scissors,
        clusterId: "edit",
        clusterLabel: "Dựng & Phong cách",
        keywords: "trinh dung freecut cat ghep timeline",
      },
      {
        href: "/video-style",
        label: "Phong cách & Âm thanh",
        icon: Palette,
        clusterId: "edit",
        clusterLabel: "Dựng & Phong cách",
        keywords: "phong cach am thanh video style phu de karaoke nhac nen",
      },
      {
        href: "/studio",
        label: "Studio AI (Remotion)",
        icon: Sparkles,
        clusterId: "edit",
        clusterLabel: "Dựng & Phong cách",
        keywords: "studio ai remotion hieu ung do hoa",
      },
    ],
  },
  {
    id: "publish",
    label: "Phát hành",
    items: [
      {
        href: "/approval",
        label: "Duyệt & Lịch đăng",
        icon: CheckCircle2,
        clusterId: "publish",
        clusterLabel: "Phát hành",
        keywords: "duyet bai lich dang kenh tiktok youtube facebook",
        badgeType: "approvals",
      },
      {
        href: "/autopilot",
        label: "Kênh tự động (Autopilot)",
        icon: Bot,
        clusterId: "publish",
        clusterLabel: "Phát hành",
        keywords: "kenh tu dong autopilot quy tac",
      },
    ],
  },
];

export const ALL_NAV_ITEMS: NavItemConfig[] = [
  OVERVIEW_NAV_ITEM,
  ...NAV_CLUSTERS.flatMap((c) => c.items),
  SETTINGS_NAV_ITEM,
  WELCOME_NAV_ITEM,
];

export function isRouteActive(pathname: string, itemHref: string): boolean {
  if (itemHref === "/") return pathname === "/";
  return pathname === itemHref || pathname.startsWith(`${itemHref}/`);
}

export function resolveRouteMeta(pathname: string): {
  clusterId: ClusterId;
  clusterLabel: string;
  itemLabel: string;
  href: string;
} {
  if (pathname.startsWith("/lipsync")) {
    return {
      clusterId: "adapt",
      clusterLabel: "Studio chuyển thể",
      itemLabel: "Nhép môi chân dung",
      href: "/lipsync",
    };
  }
  for (const item of ALL_NAV_ITEMS) {
    if (isRouteActive(pathname, item.href)) {
      return {
        clusterId: item.clusterId,
        clusterLabel: item.clusterLabel,
        itemLabel: item.label,
        href: item.href,
      };
    }
  }
  return {
    clusterId: "produce",
    clusterLabel: "Tổng quan",
    itemLabel: "Tổng quan",
    href: "/",
  };
}
