import AskPage from "@/app/workspaces/[workspaceId]/ask/page";
import { DEMO_WORKSPACE_ID } from "@/lib/api";

export default function DemoAskPage() {
  return <AskPage params={Promise.resolve({ workspaceId: DEMO_WORKSPACE_ID })} />;
}
