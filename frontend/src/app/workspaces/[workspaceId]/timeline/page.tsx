import type { Metadata } from "next";

import { PageHeader } from "@/components/layout/page-header";

export const metadata: Metadata = {
  title: "Context Timeline | 맥락이",
};

export default function TimelinePage() {
  return (
    <>
      <PageHeader
        title="Context Timeline"
        description="결정과 이벤트가 쌓인 순서를 시간축으로 따라갑니다."
      />
      {/* TODO(Day 3: Context Timeline 화면 구현) */}
      <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        준비 중입니다.
      </div>
    </>
  );
}
