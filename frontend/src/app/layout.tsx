import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Geist } from "next/font/google";

import { Toaster } from "@/components/ui/sonner";
import { cn } from "@/lib/utils";

import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });

export const metadata: Metadata = {
  title: "맥락이",
  description: "흩어진 업무의 맥락을 이어주는 AI",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="ko" className={cn("font-sans antialiased", geist.variable)}>
      <body>
        {children}
        <Toaster position="bottom-right" />
      </body>
    </html>
  );
}
