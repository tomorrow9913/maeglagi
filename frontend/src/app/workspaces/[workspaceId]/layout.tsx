"use client";

import { use, type ReactNode } from "react";
import Link from "next/link";

import { EmptyState, ErrorState, ListSkeleton } from "@/components/common/state-views";
import { WorkspaceNav } from "@/components/layout/workspace-nav";
import { Button } from "@/components/ui/button";
import { useAsync } from "@/hooks/use-async";
import { api, ApiError } from "@/lib/api";

export default function WorkspaceLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);

  /*
   * 워크스페이스가 없으면 하위 화면은 전부 "데이터 없음"처럼 보입니다.
   * 여기서 한 번 확인해 원인을 분명히 알려줍니다.
   */
  const { data, error, isLoading, reload } = useAsync(
    (signal) => api.getWorkspace(workspaceId, signal),
    [workspaceId],
  );

  const isMissing = error instanceof ApiError && error.status === 404;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 gap-8 px-5 py-8">
      <aside className="hidden w-48 shrink-0 md:block">
        <WorkspaceNav workspaceId={workspaceId} />
      </aside>
      <main className="min-w-0 flex-1">
        {isLoading ? (
          <ListSkeleton count={3} className="h-28" />
        ) : isMissing ? (
          <EmptyState
            title="워크스페이스를 찾을 수 없습니다"
            description={`'${workspaceId}' 워크스페이스가 없거나 접근할 수 없습니다.`}
            action={
              <Button asChild size="sm">
                <Link href="/workspaces">목록으로 가기</Link>
              </Button>
            }
          />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : data ? (
          children
        ) : null}
      </main>
    </div>
  );
}
