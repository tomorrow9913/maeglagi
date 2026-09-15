"use client";

import { useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/common/state-views";
import { CreateWorkspaceDialog } from "@/features/workspace/components/create-workspace-dialog";
import { useAsync } from "@/hooks/use-async";
import { api, isMockMode } from "@/lib/api";
import type { Workspace } from "@/lib/api";
import { workspacePath } from "@/lib/navigation";

export default function WorkspacesPage() {
  const router = useRouter();
  const { data, error, isLoading, reload } = useAsync((signal) => api.listWorkspaces(signal));

  // 만들자마자 바로 들어가는 편이 자연스러워 새 워크스페이스로 이동합니다.
  const onCreated = useCallback(
    (created: Workspace) => router.push(workspacePath(created.id)),
    [router],
  );

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-10">
      <PageHeader
        title="워크스페이스"
        description={
          isMockMode
            ? "맥락을 모을 공간을 고르거나 새로 만듭니다. (mock 데이터)"
            : "맥락을 모을 공간을 고르거나 새로 만듭니다."
        }
        action={<CreateWorkspaceDialog onCreated={onCreated} />}
      />

      {isLoading ? (
        <ListSkeleton count={3} />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : data && data.length === 0 ? (
        <EmptyState
          title="아직 워크스페이스가 없습니다"
          description="새 워크스페이스를 만들고 회의와 문서를 올려보세요."
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data?.map((workspace) => (
            <li key={workspace.id}>
              <Link
                href={workspacePath(workspace.id)}
                className="block rounded-xl border border-border bg-card p-5 transition-colors hover:border-foreground/30"
              >
                <p className="font-medium">{workspace.name}</p>
                <p className="mt-1 text-sm text-muted-foreground">소스 {workspace.sourceCount}개</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
