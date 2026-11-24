import type { Metadata } from "next";
import "./globals.css";
import { WorkspaceProvider } from "@/lib/api";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  title: "Video Creator V2 — AI Multi-Studio",
  description: "Multi-Workspace Short Video Production & Publishing Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi">
      <body className="antialiased">
        <WorkspaceProvider>
          <AppShell>{children}</AppShell>
        </WorkspaceProvider>
      </body>
    </html>
  );
}
