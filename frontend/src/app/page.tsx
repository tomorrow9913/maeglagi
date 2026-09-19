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
      <header className="flex flex-wrap items-center justify-between gap-3">
        <MaeglagiWordmark className="text-lg" />
        <nav
          aria-label="프로젝트 링크"
          className="flex items-center gap-4 text-sm text-muted-foreground"
        >
          <a
            href="https://github.com/tomorrow9913/maeglagi"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-foreground"
          >
            GitHub
          </a>
          <a
            href="https://github.com/tomorrow9913/maeglagi/blob/main/CONTRIBUTING.md"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-foreground"
          >
            기여하기
          </a>
        </nav>
      </header>

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
            href="/account/mcp"
            className="inline-flex h-10 items-center rounded-md border border-border px-5 text-sm font-medium transition-colors hover:bg-muted"
          >
            MCP 설정
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

      <section
        aria-labelledby="mcp-title"
        className="mt-12 rounded-2xl border border-border bg-card p-6 sm:p-8"
      >
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold tracking-wide text-primary">YOUR AGENT · MCP</p>
            <h2 id="mcp-title" className="mt-2 text-2xl font-semibold tracking-tight">
              쓰던 에이전트와 맥락이를 연결하세요
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
              맥락이는 녹음·자료·결과·온톨로지를 보관합니다. 연결한 에이전트가 전사·분석·답변을
              수행하므로 맥락이에 AI 공급자 API key를 등록하지 않아도 시작할 수 있습니다.
            </p>
          </div>
          <Link
            href="/account/mcp"
            className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            계정 MCP 연결
          </Link>
        </div>
        <div className="mt-6 grid gap-2 text-sm sm:grid-cols-[1fr_auto_1fr_auto_2fr] sm:items-center">
          <div className="rounded-lg bg-muted px-4 py-3">
            <strong className="block font-medium">내 에이전트</strong>
            <span className="text-xs text-muted-foreground">전사 · 분석 · 답변</span>
          </div>
          <span className="hidden text-muted-foreground sm:block" aria-hidden>
            →
          </span>
          <div className="rounded-lg bg-muted px-4 py-3">
            <strong className="block font-medium">MCP</strong>
            <span className="text-xs text-muted-foreground">계정 토큰으로 연결</span>
          </div>
          <span className="hidden text-muted-foreground sm:block" aria-hidden>
            →
          </span>
          <div className="rounded-lg bg-muted px-4 py-3">
            <strong className="block font-medium">맥락이 워크스페이스</strong>
            <span className="text-xs text-muted-foreground">
              소스 · 대본 · 프로젝트 · 참여자 · 결정 · 그래프
            </span>
          </div>
        </div>
        <p className="mt-4 text-xs text-muted-foreground">
          오디오 전사에는 연결한 에이전트의 음성 처리 기능이 필요합니다.
        </p>
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
