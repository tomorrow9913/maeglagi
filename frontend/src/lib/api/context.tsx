"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

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
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (USE_MOCKS) return;
    const controller = new AbortController();
    demoHttpApi.getWorkspace("", controller.signal).then((workspace) => { if (!controller.signal.aborted) { setWorkspaceId(workspace.id); setError(undefined); } }).catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "데모를 불러오지 못했습니다."); });
    return () => controller.abort();
  }, [attempt]);
  if (!workspaceId) return <div className="mx-auto max-w-xl p-8 text-sm">{error ? <div role="alert" className="space-y-3"><p>{error}</p><button type="button" className="underline" onClick={() => { setError(undefined); setAttempt((value) => value + 1); }}>다시 시도</button></div> : "데모 데이터를 불러오는 중…"}</div>;
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
