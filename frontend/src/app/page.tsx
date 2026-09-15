import Link from "next/link";

import { workspaceNavItems } from "@/lib/navigation";

const capabilities = workspaceNavItems.filter((item) =>
  ["ask", "timeline", "graph"].includes(item.segment),
);

export default function HomePage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-5 py-24">
      <section className="max-w-3xl">
        <p className="text-xs font-extrabold tracking-[0.16em] text-primary">
          ORGANIZATIONAL CONTEXT PLATFORM
        </p>
        <h1 className="mt-4 text-5xl leading-[0.98] font-semibold tracking-tighter sm:text-7xl">
          흩어진 업무의 맥락을 잇다.
        </h1>
        <p className="mt-5 max-w-2xl text-lg leading-relaxed text-muted-foreground">
          회의와 문서에서 결정, 이슈, 할 일을 연결하고 왜 그런 결정이 나왔는지 근거와 함께 답합니다.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link
            href="/demo"
            className="inline-flex h-10 items-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            데모 바로 보기
          </Link>
          <Link
            href="/workspaces"
            className="inline-flex h-10 items-center rounded-md border border-border px-5 text-sm font-medium transition-colors hover:border-foreground/30"
          >
            워크스페이스 열기
          </Link>
        </div>
      </section>

      <section aria-label="핵심 기능" className="mt-20 grid gap-4 md:grid-cols-3">
        {capabilities.map((item) => {
          const Icon = item.icon;
          return (
            <article key={item.segment} className="rounded-3xl border border-border p-7">
              <Icon className="size-5 text-primary" aria-hidden />
              <h2 className="mt-10 text-2xl font-semibold tracking-tight">{item.label}</h2>
              <p className="mt-2 leading-relaxed text-muted-foreground">{item.description}</p>
            </article>
          );
        })}
      </section>
    </main>
  );
}
