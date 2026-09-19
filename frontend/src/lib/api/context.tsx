"use client";

import { createContext, useCallback, useContext, type ReactNode } from "react";

import { demoPath, selectRouteApi } from "@/lib/demo-routing";
import { workspacePath } from "@/lib/navigation";

import { api } from "./index";
import { mockApi } from "./mock";

const ApiContext = createContext(api);
const DemoContext = createContext(false);

export function DemoApiProvider({ children }: { children: ReactNode }) {
  return (
    <DemoContext.Provider value={true}>
      <ApiContext.Provider value={selectRouteApi(true, api, mockApi)}>
        {children}
      </ApiContext.Provider>
    </DemoContext.Provider>
  );
}

export function useApi() {
  return useContext(ApiContext);
}

export function useWorkspacePath() {
  const isDemo = useContext(DemoContext);
  return useCallback(
    (workspaceId: string, segment?: string) =>
      isDemo ? demoPath(segment) : workspacePath(workspaceId, segment),
    [isDemo],
  );
}
