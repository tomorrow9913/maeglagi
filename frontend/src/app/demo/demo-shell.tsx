"use client";

import type { ReactNode } from "react";
import { AppHeader } from "@/components/layout/app-header";
import { WorkspaceLayoutView } from "@/app/workspaces/[workspaceId]/layout-view";
import { useDemoWorkspaceId } from "@/lib/api/context";

export function DemoShell({ children }: { children: ReactNode }) {
  const workspaceId = useDemoWorkspaceId();
  return <div className="flex min-h-dvh flex-col"><AppHeader /><WorkspaceLayoutView workspaceId={workspaceId}>{children}</WorkspaceLayoutView></div>;
}
