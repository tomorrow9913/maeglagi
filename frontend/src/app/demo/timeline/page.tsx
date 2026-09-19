import TimelinePage from "@/app/workspaces/[workspaceId]/timeline/page";
import { DEMO_WORKSPACE_ID } from "@/lib/api";

export default function DemoTimelinePage() {
  return <TimelinePage params={Promise.resolve({ workspaceId: DEMO_WORKSPACE_ID })} />;
}
