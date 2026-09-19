import type { ReactNode } from "react";

import { AppHeader } from "@/components/layout/app-header";
import WorkspaceLayout from "@/app/workspaces/[workspaceId]/layout";
import { DemoApiProvider } from "@/lib/api/context";
import { DEMO_WORKSPACE_ID } from "@/lib/api";

export default function DemoLayout({ children }: { children: ReactNode }) {
  return (
    <DemoApiProvider>
      <div className="flex min-h-dvh flex-col">
        <AppHeader />
        <WorkspaceLayout params={Promise.resolve({ workspaceId: DEMO_WORKSPACE_ID })}>
          {children}
        </WorkspaceLayout>
      </div>
    </DemoApiProvider>
  );
}
