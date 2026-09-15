import { redirect } from "next/navigation";

import { workspacePath } from "@/lib/navigation";

export default async function WorkspaceIndexPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  redirect(workspacePath(workspaceId, "timeline"));
}
