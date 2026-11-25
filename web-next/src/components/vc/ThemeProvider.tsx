"use client";

import * as React from "react";
import { ThemeProvider as NextThemesProvider } from "next-themes";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/overlays";

export function StudioThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      storageKey="vc.theme"
      disableTransitionOnChange
    >
      <TooltipProvider>
        {children}
        <Toaster
          position="bottom-right"
          richColors
          closeButton
          toastOptions={{
            className: "text-[13px] font-medium",
          }}
        />
      </TooltipProvider>
    </NextThemesProvider>
  );
}
