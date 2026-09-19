"use client";

import { SourcesView } from "@/app/workspaces/[workspaceId]/sources/view";
import { useDemoWorkspaceId } from "@/lib/api/context";

export default function DemoSourcesPage() {
  return <SourcesView workspaceId={useDemoWorkspaceId()} />;
}
