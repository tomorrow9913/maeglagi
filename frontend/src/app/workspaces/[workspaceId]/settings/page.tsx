"use client";

import { use, useEffect, useState } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/common/state-views";
import { ApiKeyCard } from "@/features/workspace/components/api-key-card";
import { WorkspaceModelsCard } from "@/features/workspace/components/workspace-models-card";
import { useAsync } from "@/hooks/use-async";
import { useApi } from "@/lib/api/context";
import type { AiProvider, LlmProvider } from "@/lib/api";

export default function SettingsPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const api = useApi();
  const { data, error, isLoading, reload } = useAsync(
    (signal) =>
      Promise.all([
        api.listProviderCredentials(workspaceId, signal),
        api.listWorkspaceProviders(workspaceId, signal),
      ]),
    [workspaceId],
  );
  const [selectedProvider, setSelectedProvider] = useState<LlmProvider>();
  const [modelRevision, setModelRevision] = useState(0);
  const credentials = data?.[0] ?? [];
  const providers: AiProvider[] = data?.[1] ?? [];

  useEffect(() => {
    if (!data || data[1].length === 0) return;
    setSelectedProvider((current) =>
      current && data[1].some((item) => item.id === current)
        ? current
        : (data[0].find((item) => item.isDefault)?.provider ?? data[1][0].id),
    );
  }, [data]);

  const provider =
    selectedProvider && providers.some((item) => item.id === selectedProvider)
      ? selectedProvider
      : (credentials.find((item) => item.isDefault)?.provider ?? providers[0]?.id);
  const hasCredential = credentials.some((item) => item.status === "active");

  return (
    <>
      <PageHeader title="설정" description="워크스페이스 정보와 BYOK API key를 관리합니다." />
      {isLoading && !data ? (
        <ListSkeleton count={1} className="h-40" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : providers.length === 0 ? (
        <EmptyState
          title="사용 가능한 AI provider가 없습니다"
          description="관리자에게 provider registry 설정을 확인해 달라고 요청해 주세요."
        />
      ) : (
        <div className="space-y-4">
          <ApiKeyCard
            workspaceId={workspaceId}
            credentials={credentials}
            providers={providers}
            provider={provider}
            onProviderChange={setSelectedProvider}
            onUpdated={() => {
              reload();
              setModelRevision((value) => value + 1);
            }}
          />
          {hasCredential ? (
            <WorkspaceModelsCard
              key={`${workspaceId}-${modelRevision}`}
              workspaceId={workspaceId}
              providers={providers}
            />
          ) : (
            <section className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
              사용할 모델을 보려면 위에서 API key를 등록해 주세요.
            </section>
          )}
        </div>
      )}
    </>
  );
}
