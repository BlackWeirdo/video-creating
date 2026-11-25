import type { Metadata } from "next";
import "@fontsource/be-vietnam-pro/400.css";
import "@fontsource/be-vietnam-pro/500.css";
import "@fontsource/be-vietnam-pro/600.css";
import "@fontsource/be-vietnam-pro/700.css";
import "./globals.css";
import { WorkspaceProvider } from "@/lib/api";
import { StudioThemeProvider } from "@/components/vc/ThemeProvider";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  title: "Video Creator V2 — Studio Video Đa Kênh AI",
  description: "Nền tảng sản xuất, Việt hóa và phát hành video ngắn đa thương hiệu",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi" suppressHydrationWarning>
      <body className="antialiased">
        <StudioThemeProvider>
          <WorkspaceProvider>
            <AppShell>{children}</AppShell>
          </WorkspaceProvider>
        </StudioThemeProvider>
      </body>
    </html>
  );
}
