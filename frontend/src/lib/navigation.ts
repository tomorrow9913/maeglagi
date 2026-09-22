import type { LucideIcon } from "lucide-react";
import { FileText, MessageCircleQuestion, Network, Settings, ShieldCheck, Waypoints, UsersRound } from "lucide-react";

export type WorkspaceNavItem = {
  /** `/workspaces/[workspaceId]` 아래의 상대 경로 */
  segment: string;
  label: string;
  description: string;
  icon: LucideIcon;
};

export const workspaceNavItems: WorkspaceNavItem[] = [
  {
    segment: "ask",
    label: "Ask",
    description: "워크스페이스에 질문하고 근거와 함께 답을 받습니다.",
    icon: MessageCircleQuestion,
  },
  {
    segment: "sources",
    label: "소스",
    description: "회의 녹음과 문서를 올리고 처리 상태를 확인합니다.",
    icon: FileText,
  },
  {
    segment: "directory",
    label: "참여자·프로젝트",
    description: "참여자와 프로젝트를 관리합니다.",
    icon: UsersRound,
  },
  {
    segment: "timeline",
    label: "Timeline",
    description: "결정과 이벤트가 쌓인 순서를 시간축으로 따라갑니다.",
    icon: Waypoints,
  },
  {
    segment: "graph",
    label: "Graph",
    description: "사람·프로젝트·업무의 연결을 그래프로 탐색합니다.",
    icon: Network,
  },
  {
    segment: "audit",
    label: "감사 기록",
    description: "멤버와 에이전트가 수행한 작업의 증적을 확인합니다.",
    icon: ShieldCheck,
  },
  {
    segment: "settings",
    label: "설정",
    description: "워크스페이스 정보와 BYOK API key를 관리합니다.",
    icon: Settings,
  },
];

export function workspacePath(workspaceId: string, segment?: string): string {
  const base = `/workspaces/${workspaceId}`;
  return segment ? `${base}/${segment}` : base;
}
