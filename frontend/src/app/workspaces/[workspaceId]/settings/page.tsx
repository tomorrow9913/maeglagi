"use client";

import { use, useState } from "react";
import Link from "next/link";

import { PageHeader } from "@/components/layout/page-header";
import { ErrorState, ListSkeleton } from "@/components/common/state-views";
import { ApiKeyCard } from "@/features/workspace/components/api-key-card";
import { WorkspaceModelsCard } from "@/features/workspace/components/workspace-models-card";
import { useAsync } from "@/hooks/use-async";
import { useApi } from "@/lib/api/context";
import type { AiProvider } from "@/lib/api";
import { BOOTSTRAP_AI_PROVIDERS, withOllamaProvider } from "@/lib/api";

export default function SettingsPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const api = useApi();
  const { data, error, isLoading, reload } = useAsync(
    (signal) => Promise.all([api.listAccountCredentials(signal), api.listProviders(signal)]),
    [workspaceId],
  );
  const [modelRevision, setModelRevision] = useState(0);
  const credentials = data?.[0] ?? [];
  // 서버 카탈로그가 비어 있어도 Ollama는 항상 고를 수 있으므로 공급자 목록이 비는 경우는 없습니다.
  const providers: AiProvider[] = data
    ? withOllamaProvider(data[1].length > 0 ? data[1] : BOOTSTRAP_AI_PROVIDERS).map((item) => ({
        ...item,
        configured: credentials.some(
          (credential) => credential.provider === item.id && credential.status === "active",
        ),
      }))
    : [];
  const hasCredential = credentials.some((item) => item.status === "active");

  return (
    <>
      <PageHeader
        title="설정"
        description="계정 AI 연결과 이 워크스페이스에서 쓸 모델을 관리합니다."
      />
      <section className="mb-5 rounded-xl border border-border bg-card p-5">
        <h2 className="text-sm font-semibold">내 에이전트로 작업하기</h2>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
          AI 공급자의 API key 없이 계정 MCP 연결로 에이전트가 소스와 맥락에 접근할 수 있습니다. MCP
          토큰은 워크스페이스별 설정이 아닌 계정 설정에서 관리합니다.
        </p>
        <Link
          href="/account/mcp"
          className="mt-3 inline-block text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          계정 MCP 연결 열기 →
        </Link>
      </section>
      {isLoading && !data ? (
        <ListSkeleton count={2} className="h-40" label="AI 연결을 불러오는 중" />
      ) : error && !data ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <div className="space-y-4">
          {error ? (
            <ErrorState
              compact
              error={error}
              onRetry={reload}
              title="AI 연결 목록을 새로 불러오지 못했습니다"
            />
          ) : null}
          <ApiKeyCard
            credentials={credentials}
            providers={providers}
            onUpdated={(affectsModels) => {
              reload();
              if (affectsModels) setModelRevision((value) => value + 1);
            }}
          />
          {hasCredential ? (
            <WorkspaceModelsCard
              key={workspaceId}
              workspaceId={workspaceId}
              revision={modelRevision}
              providers={providers}
              credentials={credentials}
            />
          ) : (
            <section className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
              사용할 모델을 고르려면 위에서 AI 연결을 추가해 주세요.
            </section>
          )}
        </div>
      )}
    </>
  );
}
