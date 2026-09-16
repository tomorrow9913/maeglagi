import Link from "next/link";

import { MaeglagiWordmark } from "@/components/brand/logo";
import { AnswerPreview } from "@/features/ask/components/answer-preview";
import { workspaceNavItems } from "@/lib/navigation";

const capabilities = workspaceNavItems.filter((item) =>
  ["timeline", "graph", "ask"].includes(item.segment),
);

export default function HomePage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-5 py-10">
      <MaeglagiWordmark className="text-lg" />

      <section className="mt-16 max-w-3xl sm:mt-24">
        <h1 className="text-5xl leading-tight font-semibold tracking-tighter break-keep sm:text-7xl">
          흩어진 업무의 맥락을 잇다.
        </h1>
        <p className="mt-5 max-w-2xl text-lg leading-relaxed text-muted-foreground">
          회의와 문서에서 결정, 이슈, 할 일을 연결하고 왜 그런 결정이 나왔는지 근거와 함께 답합니다.
        </p>
        <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-3">
          <Link
            href="/workspaces"
            className="inline-flex h-10 items-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            워크스페이스 열기
          </Link>
          <Link
            href="/demo"
            className="text-sm font-medium text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
          >
            예시 워크스페이스 둘러보기
          </Link>
        </div>
      </section>

      <section aria-label="답변 예시" className="mt-16">
        <AnswerPreview />
      </section>

      <dl className="mt-12 grid gap-6 border-t border-border pt-8 md:grid-cols-3">
        {capabilities.map((item) => (
          <div key={item.segment}>
            <dt className="text-sm font-semibold">{item.label}</dt>
            <dd className="mt-1 text-sm leading-relaxed text-muted-foreground">
              {item.description}
            </dd>
          </div>
        ))}
      </dl>
    </main>
  );
}
