import type { Metadata } from "next";

import { PageHeader } from "@/components/layout/page-header";

export const metadata: Metadata = {
  title: "소스 | 맥락이",
};

export default function SourcesPage() {
  return (
    <>
      <PageHeader title="소스" description="회의 녹음과 문서를 올리고 처리 상태를 확인합니다." />
      {/* TODO(Day 2: 문서 업로드·회의 녹음 UI, Day 4: 원문 뷰어) */}
      <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        준비 중입니다.
      </div>
    </>
  );
}
