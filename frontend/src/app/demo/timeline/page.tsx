"use client";

import { TimelineView } from "@/app/workspaces/[workspaceId]/timeline/view";
import { useDemoWorkspaceId } from "@/lib/api/context";

export default function DemoTimelinePage() {
  return <TimelineView workspaceId={useDemoWorkspaceId()} />;
}
