"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { ErrorState, ListSkeleton } from "@/components/common/state-views";
import { AppHeader } from "@/components/layout/app-header";
import { demoPath, selectRouteApi } from "@/lib/demo-routing";
import { workspacePath } from "@/lib/navigation";

import { api, DEMO_WORKSPACE_ID } from "./index";
import { USE_MOCKS } from "./config";
import { demoHttpApi } from "./demo-http";
import { mockApi } from "./mock";

const ApiContext = createContext(api);
const DemoContext = createContext(false);
const DemoWorkspaceContext = createContext<string | undefined>(undefined);

export function DemoApiProvider({ children }: { children: ReactNode }) {
  const [workspaceId, setWorkspaceId] = useState<string | undefined>(USE_MOCKS ? DEMO_WORKSPACE_ID : undefined);
  const [error, setError] = useState<Error>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (USE_MOCKS) return;
    const controller = new AbortController();
    demoHttpApi.getWorkspace("", controller.signal).then((workspace) => { if (!controller.signal.aborted) { setWorkspaceId(workspace.id); setError(undefined); } }).catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause : new Error(String(cause))); });
    return () => controller.abort();
  }, [attempt]);
  // 데모는 첫인상 경로입니다. 헤더를 남겨 두고 다른 화면과 같은 로딩·오류 모양을 씁니다.
  if (!workspaceId)
    return (
      <div className="flex min-h-dvh flex-col">
        <AppHeader />
        <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-8">
          {error ? (
            <ErrorState
              title="데모를 불러오지 못했습니다"
              error={error}
              onRetry={() => { setError(undefined); setAttempt((value) => value + 1); }}
            />
          ) : (
            <ListSkeleton count={3} className="h-28" label="데모 데이터를 불러오는 중" />
          )}
        </main>
      </div>
    );
  return (
    <DemoContext.Provider value={true}>
      <DemoWorkspaceContext.Provider value={workspaceId}>
        <ApiContext.Provider value={selectRouteApi(true, api, USE_MOCKS ? mockApi : demoHttpApi)}>
          {children}
        </ApiContext.Provider>
      </DemoWorkspaceContext.Provider>
    </DemoContext.Provider>
  );
}

export function useDemoWorkspaceId(): string {
  const id = useContext(DemoWorkspaceContext);
  if (!id) throw new Error("DemoApiProvider is required");
  return id;
}

export function useApi() {
  return useContext(ApiContext);
}

export function useDemoMode() {
  return useContext(DemoContext);
}

export function useWorkspacePath() {
  const isDemo = useContext(DemoContext);
  return useCallback(
    (workspaceId: string, segment?: string) =>
      isDemo ? demoPath(segment) : workspacePath(workspaceId, segment),
    [isDemo],
  );
}
