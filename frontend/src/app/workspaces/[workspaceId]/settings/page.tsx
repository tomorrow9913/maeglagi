"use client";

import { use, useEffect, useState } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/common/state-views";
import { ApiKeyCard } from "@/features/workspace/components/api-key-card";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import type { AiProvider, WorkspaceSecrets } from "@/lib/api";

export default function SettingsPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);

  const { data, error, isLoading, reload } = useAsync(
    (signal) =>
      Promise.all([
        api.getWorkspaceSecrets(workspaceId, signal),
        api.listWorkspaceProviders(workspaceId, signal),
      ]),
    [workspaceId],
  );

  // 저장 직후 화면을 다시 불러오지 않고 결과만 반영합니다.
  const [secrets, setSecrets] = useState<WorkspaceSecrets | null>(null);
  useEffect(() => setSecrets(data?.[0] ?? null), [data]);
  const providers: AiProvider[] = data?.[1] ?? [];

  return (
    <>
      <PageHeader title="설정" description="워크스페이스 정보와 BYOK API key를 관리합니다." />

      {isLoading ? (
        <ListSkeleton count={1} className="h-40" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : providers.length === 0 ? (
        <EmptyState
          title="사용 가능한 AI provider가 없습니다"
          description="관리자에게 provider registry 설정을 확인해 달라고 요청해 주세요."
        />
      ) : (
        <ApiKeyCard
          workspaceId={workspaceId}
          secrets={secrets}
          providers={providers}
          onUpdated={setSecrets}
        />
      )}
    </>
  );
}
