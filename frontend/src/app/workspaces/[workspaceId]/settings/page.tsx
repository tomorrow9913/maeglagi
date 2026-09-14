import type { Metadata } from "next";

import { PageHeader } from "@/components/layout/page-header";

export const metadata: Metadata = {
  title: "설정 | 맥락이",
};

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="설정" description="워크스페이스 정보와 BYOK API key를 관리합니다." />
      {/* TODO(Day 2: 워크스페이스 생성 및 BYOK 키 입력 폼) */}
      <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        준비 중입니다.
      </div>
    </>
  );
}
