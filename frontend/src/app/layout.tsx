import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Geist } from "next/font/google";

import { Toaster } from "@/components/ui/sonner";
import { cn } from "@/lib/utils";

import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });

// 제품 정의와 슬로건의 기준은 docs/brand.md입니다. 문구를 바꿀 때 함께 고칩니다.
export const metadata: Metadata = {
  title: "맥락이",
  description:
    "회의와 문서처럼 흩어진 업무 정보를 AI가 연결해 사람·프로젝트·결정·업무·이벤트의 관계와 현재 맥락을 자동으로 만드는 Organizational Context Platform",
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
