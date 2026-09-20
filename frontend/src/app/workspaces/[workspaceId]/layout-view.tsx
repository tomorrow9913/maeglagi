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
import { useApi, useDemoMode } from "@/lib/api/context";

export default function WorkspaceLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);
  return <WorkspaceLayoutView workspaceId={workspaceId}>{children}</WorkspaceLayoutView>;
}

export function WorkspaceLayoutView({ children, workspaceId }: { children: ReactNode; workspaceId: string }) {
  const api = useApi();
  const isDemo = useDemoMode();

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

  // 형식이 틀린 ID는 서버가 422로 거절합니다. 사용자에게는 둘 다 "없는 워크스페이스"입니다.
  const isMissing = error instanceof ApiError && (error.status === 404 || error.status === 422);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-5 py-8 md:flex-row md:gap-8">
      <aside className="w-full shrink-0 md:w-56">
        {/* 어느 워크스페이스를 보고 있는지 항상 보이게 두고, 누르면 목록에서 바꿉니다. */}
        {isLoading && !data ? (
          <Skeleton className="mb-4 h-14" />
        ) : data && isDemo ? (
          // 데모 방문자에게는 바꿀 워크스페이스가 없습니다. 링크를 두면 로그인 화면으로 넘어갑니다.
          <div className="mb-4 px-3 py-2">
            <span className="block truncate text-sm font-semibold">{data.name}</span>
            <span className="block text-xs text-muted-foreground">소스 {data.sourceCount}개</span>
          </div>
        ) : data ? (
          <Link
            href="/workspaces"
            aria-label={`${data.name} · 워크스페이스 바꾸기`}
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
        <WorkspaceSources key={workspaceId} workspaceId={workspaceId} />
      </aside>
      <main className="min-w-0 flex-1">
        {isLoading && !data ? (
          <ListSkeleton count={3} className="h-28" label="워크스페이스를 불러오는 중" />
        ) : isMissing ? (
          <EmptyState
            title="워크스페이스를 찾을 수 없습니다"
            description="주소가 잘못됐거나 접근 권한이 없는 워크스페이스입니다."
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
