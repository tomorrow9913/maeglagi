"use client";

import { useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, ErrorState } from "@/components/common/state-views";
import { SlowNotice } from "@/components/common/slow-notice";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CreateWorkspaceDialog } from "@/features/workspace/components/create-workspace-dialog";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import type { Workspace } from "@/lib/api";
import { workspacePath } from "@/lib/navigation";

export default function WorkspacesPage() {
  const router = useRouter();
  const { data, error, isLoading, reload } = useAsync((signal) => api.listWorkspaces(signal));

  // 만들자마자 바로 들어가는 편이 자연스러워 새 워크스페이스로 이동합니다.
  const onCreated = useCallback(
    (created: Workspace, mode: "agent" | "service") =>
      router.push(mode === "agent" ? "/account/mcp" : workspacePath(created.id, "ask")),
    [router],
  );

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-10">
      <PageHeader
        title="워크스페이스"
        description="맥락을 모을 공간을 고르거나 새로 만듭니다."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild size="sm" variant="outline">
              <Link href="/account/mcp">MCP 설정</Link>
            </Button>
            <CreateWorkspaceDialog onCreated={onCreated} />
          </div>
        }
      />

      {isLoading && !data ? (
        // 실제 목록과 같은 격자 모양으로 자리를 잡아 둡니다.
        <div role="status" className="space-y-3">
          <span className="sr-only">워크스페이스를 불러오는 중</span>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-hidden>
            {Array.from({ length: 3 }, (_, index) => (
              <Skeleton key={index} className="h-[5.5rem] w-full rounded-xl" />
            ))}
          </div>
          <SlowNotice />
        </div>
      ) : error && !data ? (
        <ErrorState error={error} onRetry={reload} />
      ) : data && data.length === 0 ? (
        <EmptyState
          title="아직 워크스페이스가 없습니다"
          description="새 워크스페이스를 만들고 회의와 문서를 올려보세요. 맥락이의 AI를 쓰려면 OpenAI·Anthropic 등의 API key나 Ollama 서버 주소가 하나 필요해요. 내 에이전트를 MCP로 연결한다면 없어도 됩니다."
          action={<CreateWorkspaceDialog onCreated={onCreated} />}
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data?.map((workspace) => (
            <li key={workspace.id}>
              <Link
                href={workspacePath(workspace.id)}
                className="block rounded-xl border border-border bg-card p-5 transition-colors hover:border-foreground/30"
              >
                <p className="line-clamp-2 font-medium break-words" title={workspace.name}>
                  {workspace.name}
                </p>
                <p className="mt-1 text-sm text-muted-foreground">소스 {workspace.sourceCount}개</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
