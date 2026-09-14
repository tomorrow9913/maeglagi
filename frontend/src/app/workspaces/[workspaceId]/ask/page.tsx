import type { Metadata } from "next";

import { PageHeader } from "@/components/layout/page-header";

export const metadata: Metadata = {
  title: "Ask Workspace | 맥락이",
};

export default function AskPage() {
  return (
    <>
      <PageHeader
        title="Ask Workspace"
        description="워크스페이스에 질문하고 근거와 함께 답을 받습니다."
      />
      {/* TODO(Day 4: 질의 및 스트리밍 답변 구현) */}
      <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        준비 중입니다.
      </div>
    </>
  );
}
