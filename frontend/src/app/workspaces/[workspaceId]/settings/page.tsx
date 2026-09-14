"use client";

import { use, useEffect, useState } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiKeyCard } from "@/features/workspace/components/api-key-card";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import type { WorkspaceSecrets } from "@/lib/api";

export default function SettingsPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);

  const { data, error, isLoading, reload } = useAsync(
    (signal) => api.getWorkspaceSecrets(workspaceId, signal),
    [workspaceId],
  );

  // 저장 직후 화면을 다시 불러오지 않고 결과만 반영합니다.
  const [secrets, setSecrets] = useState<WorkspaceSecrets | null>(null);
  useEffect(() => setSecrets(data ?? null), [data]);

  return (
    <>
      <PageHeader title="설정" description="워크스페이스 정보와 BYOK API key를 관리합니다." />

      {isLoading ? (
        <Skeleton className="h-40 w-full rounded-xl" />
      ) : error ? (
        <div className="rounded-xl border border-border bg-card p-10 text-center">
          <p className="text-sm">{error.message}</p>
          <Button variant="outline" size="sm" className="mt-4" onClick={reload}>
            다시 시도
          </Button>
        </div>
      ) : (
        <ApiKeyCard workspaceId={workspaceId} secrets={secrets} onUpdated={setSecrets} />
      )}
    </>
  );
}
