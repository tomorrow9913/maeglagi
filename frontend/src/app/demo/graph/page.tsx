"use client";

import { GraphView } from "@/app/workspaces/[workspaceId]/graph/view";
import { useDemoWorkspaceId } from "@/lib/api/context";

export default function DemoGraphPage() {
  return <GraphView workspaceId={useDemoWorkspaceId()} />;
}
