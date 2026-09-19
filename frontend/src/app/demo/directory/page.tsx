"use client";

import { DirectoryView } from "@/app/workspaces/[workspaceId]/directory/view";
import { useDemoWorkspaceId } from "@/lib/api/context";

export default function DemoDirectoryPage() {
  return <DirectoryView workspaceId={useDemoWorkspaceId()} />;
}
