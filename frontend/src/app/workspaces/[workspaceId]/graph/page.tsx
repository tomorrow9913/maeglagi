import type { Metadata } from "next";

import { PageHeader } from "@/components/layout/page-header";

export const metadata: Metadata = {
  title: "Knowledge Graph | 맥락이",
};

export default function GraphPage() {
  return (
    <>
      <PageHeader
        title="Knowledge Graph"
        description="사람·프로젝트·업무의 연결을 그래프로 탐색합니다."
      />
      {/* TODO(Day 3: Knowledge Graph 뷰 구현) */}
      <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        준비 중입니다.
      </div>
    </>
  );
}
