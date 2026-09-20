import Link from "next/link";

import { DemoAuthGuidance } from "@/components/layout/demo-auth-guidance";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { AnswerPreview } from "@/features/ask/components/answer-preview";
import { demoPath } from "@/lib/demo-routing";

/** 데모 메뉴와 같은 이름을 씁니다. 질문은 막혀 있으므로 볼 수 있는 화면으로 바로 안내합니다. */
const shortcuts = [
  { segment: "sources", label: "소스" },
  { segment: "directory", label: "참여자·프로젝트" },
  { segment: "timeline", label: "Timeline" },
  { segment: "graph", label: "Graph" },
];

export default function DemoAskPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Ask"
        description="데모에서는 질문을 실행하지 않아요. 복사한 내 워크스페이스에서 물어볼 수 있어요."
      />

      <section aria-labelledby="demo-ask-example" className="space-y-3">
        <h2 id="demo-ask-example" className="text-sm font-medium">
          답변 예시
        </h2>
        <p className="text-sm text-muted-foreground">
          질문하면 이렇게 근거와 함께 답해요. 인용 번호나 근거를 누르면 원문으로 이동합니다.
        </p>
        <AnswerPreview />
      </section>

      <section aria-labelledby="demo-ask-shortcuts" className="space-y-3">
        <h2 id="demo-ask-shortcuts" className="text-sm font-medium">
          데모에서 볼 수 있는 화면
        </h2>
        <div className="flex flex-wrap gap-2">
          {shortcuts.map((item) => (
            <Button key={item.segment} asChild variant="outline">
              <Link href={demoPath(item.segment)}>{item.label}</Link>
            </Button>
          ))}
        </div>
      </section>

      <DemoAuthGuidance />
    </div>
  );
}
