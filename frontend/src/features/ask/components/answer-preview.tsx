"use client";

import { useRouter } from "next/navigation";

import { answers } from "@/lib/api/mock/fixtures";
import type { AnswerSource } from "@/lib/api";
import { demoPath } from "@/lib/demo-routing";

import { AnswerBody } from "./answer-body";
import { MaeglagiAvatar } from "./maeglagi-avatar";
import { SourceCard } from "./source-card";

const QUESTION = "벡터 검색 대신 hybrid retrieval로 바꾼 이유가 뭐였죠?";
const EXAMPLE = answers[0];

/**
 * 랜딩에서 제품이 실제로 하는 일을 보여주는 답변 한 건입니다.
 *
 * 기능 소개 카드 대신 Ask 화면과 같은 컴포넌트로 그려, 첫 화면에서 곧바로
 * "근거와 함께 답한다"는 약속을 확인하게 합니다. 인용이나 근거를 누르면
 * 시드 워크스페이스의 원문 구간으로 이동합니다.
 */
export function AnswerPreview() {
  const router = useRouter();

  const openSource = (source: AnswerSource) => {
    const query = new URLSearchParams({ source: source.sourceId });
    if (source.chunkId) query.set("chunk", source.chunkId);
    router.push(`${demoPath("sources")}?${query.toString()}`);
  };

  return (
    <figure className="grid gap-6 rounded-2xl border border-border bg-card p-6 md:grid-cols-5 md:p-8">
      <div className="space-y-4 md:col-span-3">
        <div className="flex justify-end">
          <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2 text-sm text-primary-foreground">
            {QUESTION}
          </p>
        </div>
        <div className="flex gap-3">
          <MaeglagiAvatar />
          <AnswerBody text={EXAMPLE.text} sources={EXAMPLE.sources} onOpenSource={openSource} />
        </div>
      </div>

      <div className="md:col-span-2">
        <figcaption className="mb-2 text-xs font-medium text-muted-foreground">
          근거 {EXAMPLE.sources.length}건
        </figcaption>
        <ul className="space-y-2">
          {EXAMPLE.sources.map((source) => (
            <li key={source.index}>
              <SourceCard
                index={source.index}
                kind={source.kind}
                title={source.title}
                excerpt={source.excerpt}
                onOpen={() => openSource(source)}
              />
            </li>
          ))}
        </ul>
      </div>
    </figure>
  );
}
