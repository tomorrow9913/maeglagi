"use client";

import type { ReactNode } from "react";
import { AppHeader } from "@/components/layout/app-header";
import WorkspaceLayout from "@/app/workspaces/[workspaceId]/layout";
import { useDemoWorkspaceId } from "@/lib/api/context";

export function DemoShell({ children }: { children: ReactNode }) {
  const workspaceId = useDemoWorkspaceId();
  return <div className="flex min-h-dvh flex-col"><AppHeader /><WorkspaceLayout params={Promise.resolve({ workspaceId })}>{children}</WorkspaceLayout></div>;
}
