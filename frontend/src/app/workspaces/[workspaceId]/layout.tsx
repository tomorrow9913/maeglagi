"use client";

import { use, useEffect, type ReactNode } from "react";
import Link from "next/link";
import { ChevronsUpDown } from "lucide-react";

import { EmptyState, ErrorState, ListSkeleton } from "@/components/common/state-views";
import { WorkspaceSources } from "@/features/source-ingestion/components/workspace-sources";
import { WorkspaceNav } from "@/components/layout/workspace-nav";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAsync } from "@/hooks/use-async";
import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/api/context";

export default function WorkspaceLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);
  const api = useApi();

  /*
   * 워크스페이스가 없으면 하위 화면은 전부 "데이터 없음"처럼 보입니다.
   * 여기서 한 번 확인해 원인을 분명히 알려줍니다.
   */
  const { data, error, isLoading, reload } = useAsync(
    (signal) => api.getWorkspace(workspaceId, signal),
    [workspaceId],
  );

  useEffect(() => {
    window.addEventListener("maeglagi:sources-changed", reload);
    return () => window.removeEventListener("maeglagi:sources-changed", reload);
  }, [reload]);

  const isMissing = error instanceof ApiError && error.status === 404;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-5 py-8 md:flex-row md:gap-8">
      <aside className="w-full shrink-0 md:w-56">
        {/* 어느 워크스페이스를 보고 있는지 항상 보이게 두고, 누르면 목록에서 바꿉니다. */}
        {isLoading && !data ? (
          <Skeleton className="mb-4 h-14" />
        ) : data ? (
          <Link
            href="/workspaces"
            title="워크스페이스 바꾸기"
            className="mb-4 flex items-center gap-2 rounded-md px-3 py-2 transition-colors hover:bg-accent/50"
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">{data.name}</span>
              <span className="block text-xs text-muted-foreground">소스 {data.sourceCount}개</span>
            </span>
            <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          </Link>
        ) : null}
        <WorkspaceNav workspaceId={workspaceId} />
        <div className="hidden md:block">
          <WorkspaceSources key={workspaceId} workspaceId={workspaceId} />
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        {isLoading && !data ? (
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
        ) : error && !data ? (
          <ErrorState error={error} onRetry={reload} />
        ) : data ? (
          children
        ) : null}
      </main>
    </div>
  );
}
