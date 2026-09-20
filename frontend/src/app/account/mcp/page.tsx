"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { Check, Copy, Loader2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, ListSkeleton } from "@/components/common/state-views";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useAsync } from "@/hooks/use-async";
import { useApi } from "@/lib/api/context";
import { MCP_ENDPOINT_URL } from "@/lib/api/config";
import type { CreatedMcpToken, McpToken } from "@/lib/api";
import { toUserMessage } from "@/lib/api/error-message";

const dateLabel = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium" }).format(new Date(value))
    : "아직 없음";

const TOKEN_PERIODS = [
  { days: 7, label: "7일" },
  { days: 30, label: "30일" },
  { days: 90, label: "90일" },
  { days: 365, label: "1년" },
] as const;

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 2000);
        } catch {
          toast.error("복사하지 못했습니다. 직접 선택해 복사해 주세요.");
        }
      }}
    >
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      {copied ? "복사됨" : label}
    </Button>
  );
}

export default function AccountMcpPage() {
  const api = useApi();
  const { data, error, isLoading, reload } = useAsync((signal) => api.listMcpTokens(signal));
  const [createOpen, setCreateOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [expiresInDays, setExpiresInDays] = useState(90);
  const [created, setCreated] = useState<CreatedMcpToken | null>(null);
  const [busy, setBusy] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<McpToken | null>(null);

  const closeCreate = () => {
    setCreateOpen(false);
    setCreated(null);
    setLabel("");
    setExpiresInDays(90);
  };

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || !label.trim()) return;
    setBusy(true);
    try {
      const result = await api.createMcpToken({ label: label.trim(), expiresInDays });
      setCreated(result);
      reload();
      toast.success("MCP 토큰을 만들었습니다.");
    } catch (cause) {
      toast.error(toUserMessage(cause, "토큰을 만들지 못했습니다."));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    if (!revokeTarget || busy) return;
    setBusy(true);
    try {
      await api.revokeMcpToken(revokeTarget.id);
      setRevokeTarget(null);
      reload();
      toast.success("MCP 토큰을 해지했습니다.");
    } catch (cause) {
      toast.error(toUserMessage(cause, "토큰을 해지하지 못했습니다."));
    } finally {
      setBusy(false);
    }
  };

  const example = JSON.stringify(
    {
      mcpServers: {
        maeglagi: { url: MCP_ENDPOINT_URL, headers: { Authorization: "Bearer <MCP_TOKEN>" } },
      },
    },
    null,
    2,
  );

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 px-5 py-10">
      <div className="mb-5 text-sm text-muted-foreground">
        <Link href="/workspaces" className="hover:text-foreground hover:underline">
          워크스페이스
        </Link>
        <span aria-hidden> / </span>계정 MCP 연결
      </div>
      <PageHeader
        title="계정 MCP 연결"
        description="내 에이전트를 맥락이 계정에 연결합니다. 이 설정은 모든 워크스페이스에 적용됩니다."
        action={
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus aria-hidden />
            토큰 만들기
          </Button>
        }
      />

      <div className="grid gap-5 lg:grid-cols-[1.2fr_1fr]">
        <section
          className="rounded-xl border border-border bg-card p-5"
          aria-labelledby="mcp-setup-title"
        >
          <h2 id="mcp-setup-title" className="text-base font-semibold">
            에이전트 연결 방법
          </h2>
          <ol className="mt-4 space-y-3 text-sm leading-relaxed">
            <li>
              <span className="font-medium">1. 토큰 만들기</span>
              <p className="text-muted-foreground">
                발급 직후 한 번만 표시됩니다. 에이전트의 보안 설정에 복사해 두세요.
              </p>
            </li>
            <li>
              <span className="font-medium">2. MCP 서버 등록</span>
              <p className="text-muted-foreground">
                에이전트가 HTTP MCP 서버와 Bearer 헤더를 지원해야 합니다. 사용하는 클라이언트 형식에
                맞춰 아래 값을 넣으세요.
              </p>
            </li>
            <li>
              <span className="font-medium">3. 워크스페이스 선택</span>
              <p className="text-muted-foreground">
                에이전트가 소스·대본·프로젝트·참여자·결정·그래프를 읽고 결과를 저장할 수 있습니다.
              </p>
            </li>
          </ol>
          <div className="mt-5 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium text-muted-foreground">MCP endpoint</p>
              <CopyButton value={MCP_ENDPOINT_URL} label="주소 복사" />
            </div>
            <code className="block overflow-x-auto rounded-md bg-muted px-3 py-2 text-xs">
              {MCP_ENDPOINT_URL}
            </code>
            <p className="pt-2 text-xs font-medium text-muted-foreground">
              설정 예시 · 클라이언트별 키 이름은 다를 수 있습니다
            </p>
            <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs leading-relaxed">
              <code>{example}</code>
            </pre>
            <CopyButton value={example} label="예시 복사" />
          </div>
          <p className="mt-5 border-t border-border pt-4 text-xs leading-relaxed text-muted-foreground">
            맥락이는 녹음·자료·결과·온톨로지를 보관합니다. 전사·분석·답변은 연결한 에이전트가
            수행하므로 서비스 AI 공급자 API key는 필요하지 않습니다. 오디오는 에이전트의 음성 처리
            기능이 필요합니다.
          </p>
        </section>

        <section
          className="rounded-xl border border-border bg-card p-5"
          aria-labelledby="mcp-tokens-title"
        >
          <h2 id="mcp-tokens-title" className="text-base font-semibold">
            발급한 토큰
          </h2>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            토큰은 계정의 모든 워크스페이스에 접근할 수 있습니다. 사용하지 않는 토큰은 해지하세요.
            발급할 때 유효 기간을 선택할 수 있습니다.
          </p>
          {isLoading && !data ? (
            <ListSkeleton count={2} className="mt-4 h-20" />
          ) : error ? (
            <div className="mt-4">
              <ErrorState error={error} onRetry={reload} />
            </div>
          ) : !data?.items.length ? (
            <p className="mt-6 rounded-lg border border-dashed border-border p-5 text-center text-sm text-muted-foreground">
              아직 발급한 토큰이 없습니다.
            </p>
          ) : (
            <ul className="mt-4 divide-y divide-border">
              {data.items.map((item) => (
                <li
                  key={item.id}
                  className="flex items-start justify-between gap-3 py-4 first:pt-0"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{item.label}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      끝자리 ····{item.tokenHint} · {new Date(item.expiresAt).getTime() <= Date.now() ? "만료됨" : "만료"} {dateLabel(item.expiresAt)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      생성 {dateLabel(item.createdAt)} · 마지막 사용 {dateLabel(item.lastUsedAt)}
                    </p>
                  </div>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={`${item.label} 토큰 해지`}
                    title="토큰 해지"
                    onClick={() => setRevokeTarget(item)}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          if (!open && !busy) closeCreate();
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{created ? "토큰을 지금 복사하세요" : "MCP 토큰 만들기"}</DialogTitle>
            <DialogDescription>
              {created
                ? "이 토큰 값은 다시 볼 수 없습니다. 창을 닫으면 화면에서도 지워집니다."
                : "알아보기 쉬운 이름을 정하세요. 토큰은 계정의 모든 워크스페이스에 접근할 수 있습니다."}
            </DialogDescription>
          </DialogHeader>
          {created ? (
            <div className="space-y-3">
              <code
                className="block overflow-x-auto rounded-md bg-muted px-3 py-3 text-xs"
                aria-label="새 MCP 토큰"
              >
                {created.token}
              </code>
              <div className="flex items-center gap-2">
                <CopyButton value={created.token} label="토큰 복사" />
                <span className="text-xs text-muted-foreground">
                  만료 {dateLabel(created.item.expiresAt)}
                </span>
              </div>
            </div>
          ) : (
            <form id="create-mcp-token" className="space-y-2" onSubmit={create}>
              <label htmlFor="mcp-token-label" className="text-sm font-medium">
                토큰 이름
              </label>
              <Input
                id="mcp-token-label"
                autoFocus
                maxLength={80}
                required
                placeholder="예: 개인 에이전트"
                value={label}
                disabled={busy}
                onChange={(event) => setLabel(event.target.value)}
              />
              <label htmlFor="mcp-token-period" className="block pt-2 text-sm font-medium">
                유효 기간
              </label>
              <select
                id="mcp-token-period"
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={expiresInDays}
                disabled={busy}
                onChange={(event) => setExpiresInDays(Number(event.target.value))}
              >
                {TOKEN_PERIODS.map((period) => (
                  <option key={period.days} value={period.days}>{period.label}</option>
                ))}
              </select>
            </form>
          )}
          <DialogFooter>
            {created ? (
              <Button onClick={closeCreate}>완료</Button>
            ) : (
              <Button type="submit" form="create-mcp-token" disabled={busy || !label.trim()}>
                {busy ? <Loader2 className="animate-spin" aria-hidden /> : null}만들기
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(revokeTarget)}
        onOpenChange={(open) => {
          if (!open && !busy) setRevokeTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>토큰을 해지할까요?</DialogTitle>
            <DialogDescription>
              {revokeTarget?.label} 연결을 사용하는 에이전트의 접근이 즉시 중단됩니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRevokeTarget(null)} disabled={busy}>
              취소
            </Button>
            <Button variant="destructive" onClick={() => void revoke()} disabled={busy}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : null}해지
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}
