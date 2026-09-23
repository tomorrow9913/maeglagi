"use client";

import { use, useMemo, useState } from "react";

import { EmptyState, ErrorState, ListSkeleton } from "@/components/common/state-views";
import { Badge } from "@/components/ui/badge";
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

function analysisModelSummary(action: string, details: Record<string, unknown>): string | null {
  if (action !== "analysis.completed") return null;
  const provider = typeof details.provider === "string" ? details.provider : null;
  const model = typeof details.model === "string" ? details.model : null;
  if (provider && model) return `${provider} / ${model}`;
  if (model) return model;
  if (details.generationMethod === "external_agent") return "외부 에이전트 · 모델 미보고";
  if (details.generationMethod === "direct_edit") return "직접 편집";
  return "모델 정보 없음";
}

export default function AuditPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const api = useApi();
  const [query, setQuery] = useState("");
  const [origin, setOrigin] = useState("all");
  const [action, setAction] = useState("all");
  const audit = useAsync(
    (signal) => api.listWorkspaceAuditEvents(workspaceId, signal),
    [workspaceId],
  );

  const filteredEvents = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("ko-KR");
    return (audit.data ?? []).filter((event) => {
      if (origin !== "all" && event.origin !== origin) return false;
      if (action !== "all" && event.action !== action) return false;
      if (!needle) return true;
      const searchable = [
        event.actorEmail,
        event.actorId,
        event.origin,
        event.action,
        actionLabel[event.action],
        event.targetType,
        event.targetId,
        ...Object.values(event.details).filter(
          (value): value is string | number =>
            typeof value === "string" || typeof value === "number",
        ),
      ];
      return searchable.some((value) =>
        String(value ?? "")
          .toLocaleLowerCase("ko-KR")
          .includes(needle),
      );
    });
  }, [action, audit.data, origin, query]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">감사 기록</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          팀원과 MCP 에이전트가 수행한 작업의 증적을 확인합니다.
        </p>
      </header>

      <div className="grid gap-3 rounded-xl border bg-card p-4 md:grid-cols-[minmax(240px,1fr)_180px_220px]">
        <Input
          aria-label="감사 기록 검색"
          placeholder="계정명, 모델명, 활동, 대상 검색"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <Select value={origin} onValueChange={setOrigin}>
          <SelectTrigger aria-label="활동 경로">
            <SelectValue placeholder="모든 활동 경로" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">모든 활동 경로</SelectItem>
            <SelectItem value="web">WEB</SelectItem>
            <SelectItem value="mcp">MCP</SelectItem>
            <SelectItem value="api">API</SelectItem>
            <SelectItem value="system">SYSTEM</SelectItem>
          </SelectContent>
        </Select>
        <Select value={action} onValueChange={setAction}>
          <SelectTrigger aria-label="작업 유형">
            <SelectValue placeholder="모든 작업 유형" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">모든 작업 유형</SelectItem>
            {Object.entries(actionLabel).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

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
        ) : !filteredEvents.length ? (
          <EmptyState title="검색 결과가 없습니다" description="검색어나 필터를 변경해 보세요." />
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
                    분석 방식/모델
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
                {filteredEvents.map((event) => {
                  const summary = detailSummary(event.details);
                  const analysisModel = analysisModelSummary(event.action, event.details);
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
                      <td className="max-w-64 px-3 py-2.5 text-xs">{analysisModel ?? "—"}</td>
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
