"use client";

import { use, useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";

import { EmptyState, ErrorState, ListSkeleton } from "@/components/common/state-views";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAsync } from "@/hooks/use-async";
import { useApi } from "@/lib/api/context";

const actionLabel: Record<string, string> = {
  "workspace.created": "워크스페이스 생성",
  "member.invited": "멤버 초대",
  "member.role_changed": "멤버 권한 변경",
  "member.removed": "멤버 제거",
  "source.created": "소스 등록",
  "source.confirmed": "회의록 확인",
  "source.edited": "자료 편집",
  "transcript.edited": "회의록 편집",
  "analysis.requested": "분석 요청",
  "analysis.completed": "분석 완료",
  "transcription.completed": "음성 변환 완료",
  "embedding.completed": "임베딩 완료",
  "embedding.skipped": "임베딩 생략",
  "ask.asked": "질문",
  "person.created": "참여자 등록",
  "person.updated": "참여자 수정",
  "project.created": "프로젝트 등록",
  "project.updated": "프로젝트 수정",
  "project.participants_updated": "프로젝트 참여자 변경",
  "credential.created": "워크스페이스 AI 연결 등록",
  "credential.rotated": "워크스페이스 AI 연결 수정",
  "credential.default_changed": "기본 AI 연결 변경",
  "credential.deleted": "워크스페이스 AI 연결 삭제",
};

function detailSummary(details: Record<string, unknown>): string | null {
  const methodLabel: Record<string, string> = {
    direct_edit: "직접 편집",
    service_model: "서비스 모델",
    external_agent: "외부 에이전트 분석",
    external_agent_edit: "외부 에이전트 편집",
    lexical_fallback: "키워드 검색 대체",
  };
  const values = [
    typeof details.generationMethod === "string"
      ? (methodLabel[details.generationMethod] ?? details.generationMethod)
      : null,
    typeof details.provider === "string" ? `프로바이더 ${details.provider}` : null,
    typeof details.label === "string" ? `연결 ${details.label}` : null,
    typeof details.model === "string" ? `모델 ${details.model}` : null,
    typeof details.agentName === "string" ? `에이전트 ${details.agentName}` : null,
    details.provenanceTrust === "self_reported" ? "에이전트 신고 정보" : null,
    typeof details.chunkCount === "number" ? `청크 ${details.chunkCount}개` : null,
    details.credentialScope === "workspace"
      ? "워크스페이스 키"
      : details.credentialScope === "account"
        ? "개인 키"
        : null,
    typeof details.kind === "string" ? `유형 ${details.kind}` : null,
    typeof details.role === "string" ? `권한 ${details.role}` : null,
    typeof details.before === "string" && typeof details.after === "string"
      ? `${details.before} → ${details.after}`
      : null,
  ].filter(Boolean);
  return values.length ? values.join(" · ") : null;
}

export default function AuditPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const api = useApi();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "editor" | "viewer">("editor");
  const [busy, setBusy] = useState(false);
  const workspace = useAsync((signal) => api.getWorkspace(workspaceId, signal), [workspaceId]);
  const members = useAsync(
    (signal) => api.listWorkspaceMembers(workspaceId, signal),
    [workspaceId],
  );
  const audit = useAsync(
    (signal) => api.listWorkspaceAuditEvents(workspaceId, signal),
    [workspaceId],
  );

  const invite = async () => {
    if (!email.trim()) return;
    setBusy(true);
    try {
      await api.inviteWorkspaceMember(workspaceId, { email: email.trim(), role });
      setEmail("");
      toast.success("워크스페이스 멤버를 초대했습니다.");
      members.reload();
      audit.reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "초대하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const canManage = workspace.data?.role === "owner" || workspace.data?.role === "admin";

  const changeRole = async (memberId: string, nextRole: "admin" | "editor" | "viewer") => {
    try {
      await api.updateWorkspaceMember(workspaceId, memberId, nextRole);
      toast.success("멤버 권한을 변경했습니다.");
      members.reload();
      audit.reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "권한을 변경하지 못했습니다.");
    }
  };

  const remove = async (memberId: string) => {
    try {
      await api.removeWorkspaceMember(workspaceId, memberId);
      toast.success("멤버를 제거했습니다.");
      members.reload();
      audit.reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "멤버를 제거하지 못했습니다.");
    }
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">감사 기록</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          팀원과 MCP 에이전트가 수행한 작업의 증적을 확인합니다.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">워크스페이스 공유</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {canManage ? (
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                aria-label="초대 이메일"
                placeholder="team@example.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
              <Select value={role} onValueChange={(value) => setRole(value as typeof role)}>
                <SelectTrigger className="sm:w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="admin">관리자</SelectItem>
                  <SelectItem value="editor">편집자</SelectItem>
                  <SelectItem value="viewer">조회자</SelectItem>
                </SelectContent>
              </Select>
              <Button disabled={busy || !email.trim()} onClick={() => void invite()}>
                초대
              </Button>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              멤버 초대와 권한 변경은 소유자와 관리자만 할 수 있습니다.
            </p>
          )}
          {members.error ? (
            <ErrorState error={members.error} onRetry={members.reload} />
          ) : members.isLoading && !members.data ? (
            <ListSkeleton count={2} label="멤버를 불러오는 중" />
          ) : (
            <ul className="divide-y rounded-md border">
              {(members.data ?? []).map((member) => (
                <li
                  key={member.id}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                >
                  <span className="min-w-0 truncate">{member.email || "워크스페이스 소유자"}</span>
                  <div className="flex items-center gap-2">
                    {canManage && member.role !== "owner" ? (
                      <Select
                        value={member.role}
                        onValueChange={(value) =>
                          void changeRole(member.id, value as "admin" | "editor" | "viewer")
                        }
                      >
                        <SelectTrigger className="h-8 w-28" aria-label={`${member.email} 권한`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="admin">관리자</SelectItem>
                          <SelectItem value="editor">편집자</SelectItem>
                          <SelectItem value="viewer">조회자</SelectItem>
                        </SelectContent>
                      </Select>
                    ) : (
                      <Badge variant="secondary">{member.role}</Badge>
                    )}
                    <span className="text-xs text-muted-foreground">
                      {member.joinedAt ? "참여 중" : "초대 대기"}
                    </span>
                    {canManage && member.role !== "owner" ? (
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`${member.email} 제거`}
                        onClick={() => void remove(member.id)}
                      >
                        <Trash2 className="size-4" aria-hidden />
                      </Button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">활동</h2>
        {audit.error ? (
          <ErrorState error={audit.error} onRetry={audit.reload} />
        ) : audit.isLoading && !audit.data ? (
          <ListSkeleton count={4} label="감사 기록을 불러오는 중" />
        ) : !audit.data?.length ? (
          <EmptyState
            title="아직 감사 기록이 없습니다"
            description="멤버 초대, 자료 등록, 질문과 분석 기록이 이곳에 쌓입니다."
          />
        ) : (
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="border-b bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    시간
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    사용자
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    경로
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    작업
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    대상
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    세부 내용
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {audit.data.map((event) => {
                  const summary = detailSummary(event.details);
                  return (
                    <tr key={event.id} className="align-top hover:bg-muted/20">
                      <td className="px-3 py-2.5 text-xs whitespace-nowrap text-muted-foreground">
                        <time dateTime={event.createdAt}>
                          {new Date(event.createdAt).toLocaleString("ko-KR")}
                        </time>
                      </td>
                      <td
                        className="max-w-52 truncate px-3 py-2.5"
                        title={event.actorEmail ?? "시스템 사용자"}
                      >
                        {event.actorEmail ?? "시스템 사용자"}
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge variant="secondary">{event.origin.toUpperCase()}</Badge>
                      </td>
                      <td className="px-3 py-2.5 font-medium whitespace-nowrap">
                        {actionLabel[event.action] ?? event.action}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground">
                        <span>{event.targetType}</span>
                        {event.targetId ? (
                          <span
                            className="block max-w-44 truncate font-mono"
                            title={event.targetId}
                          >
                            {event.targetId}
                          </span>
                        ) : null}
                      </td>
                      <td className="max-w-64 px-3 py-2.5 text-xs text-muted-foreground">
                        {summary ?? "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
