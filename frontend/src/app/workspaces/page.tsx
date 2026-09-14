"use client";

import Link from "next/link";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAsync } from "@/hooks/use-async";
import { api, isMockMode } from "@/lib/api";
import { workspacePath } from "@/lib/navigation";

export default function WorkspacesPage() {
  const { data, error, isLoading, reload } = useAsync((signal) => api.listWorkspaces(signal));

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-10">
      <PageHeader
        title="워크스페이스"
        description={
          isMockMode
            ? "맥락을 모을 공간을 고르거나 새로 만듭니다. (mock 데이터)"
            : "맥락을 모을 공간을 고르거나 새로 만듭니다."
        }
      />

      {isLoading ? (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((key) => (
            <li key={key}>
              <Skeleton className="h-24 w-full rounded-xl" />
            </li>
          ))}
        </ul>
      ) : error ? (
        <div className="rounded-xl border border-border bg-card p-10 text-center">
          <p className="text-sm">{error.message}</p>
          <Button variant="outline" size="sm" className="mt-4" onClick={reload}>
            다시 시도
          </Button>
        </div>
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
