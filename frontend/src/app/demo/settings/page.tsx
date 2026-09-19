import SettingsPage from "@/app/workspaces/[workspaceId]/settings/page";
import { DEMO_WORKSPACE_ID } from "@/lib/api";

export default function DemoSettingsPage() {
  return <SettingsPage params={Promise.resolve({ workspaceId: DEMO_WORKSPACE_ID })} />;
}
