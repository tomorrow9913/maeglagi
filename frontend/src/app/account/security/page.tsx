"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Link2, Loader2 } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { kakaoIdentityLinkOptions } from "@/lib/auth-redirect";
import { apiFetch } from "@/lib/api/client";
import { createClient } from "@/lib/supabase/client";

type AccountState = {
  email: string | null;
  hasKakao: boolean;
};

export default function AccountSecurityPage() {
  const [account, setAccount] = useState<AccountState | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteText, setDeleteText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      const { data, error } = await createClient().auth.getUser();
      if (error || !data.user) {
        setMessage("계정 정보를 불러오지 못했습니다.");
        return;
      }
      setAccount({
        email: data.user.email ?? null,
        hasKakao: data.user.identities?.some((identity) => identity.provider === "kakao") ?? false,
      });
    };
    void load();

    if (new URLSearchParams(window.location.search).get("error") === "identity_link") {
      setMessage(
        "카카오 계정을 연결하지 못했습니다. 이미 다른 맥락이 계정에 연결된 카카오 계정인지 확인해 주세요.",
      );
    }
  }, []);

  const linkKakao = async () => {
    setPending(true);
    setMessage(null);
    const { error } = await createClient().auth.linkIdentity(
      kakaoIdentityLinkOptions(window.location.origin),
    );
    if (error) {
      setMessage(error.message);
      setPending(false);
    }
  };

  const deleteAccount = async () => {
    if (deleteText !== "계정 탈퇴" || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await apiFetch<void>("/auth/me", {
        method: "DELETE",
        body: JSON.stringify({ confirmation: deleteText }),
      });
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "계정을 삭제하지 못했습니다.");
      setDeleting(false);
      return;
    }
    await createClient().auth.signOut({ scope: "local" });
    window.location.assign("/");
  };

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-5 py-10">
      <div className="mb-5 text-sm text-muted-foreground">
        <Link href="/workspaces" className="hover:text-foreground hover:underline">
          워크스페이스
        </Link>
        <span aria-hidden> / </span>계정 보안
      </div>
      <PageHeader
        title="계정 보안"
        description="여러 로그인 방법을 하나의 맥락이 계정에 연결합니다."
      />

      <section className="rounded-xl border border-border bg-card p-6">
        <h2 className="text-base font-semibold">로그인 방법</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          이 화면에서 연결하면 이메일 로그인과 카카오 로그인이 동일한 회원 ID를 사용합니다.
          워크스페이스와 업로드 자료도 그대로 유지됩니다.
        </p>

        {!account && !message && (
          <div className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            계정 정보를 불러오는 중…
          </div>
        )}

        {account && (
          <div className="mt-6 space-y-4">
            <div className="rounded-lg border border-border p-4">
              <p className="text-sm font-medium">이메일</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {account.email ?? "연결된 이메일 없음"}
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border p-4">
              <div>
                <p className="text-sm font-medium">카카오</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {account.hasKakao ? "이 계정에 연결됨" : "아직 연결되지 않음"}
                </p>
              </div>
              {account.hasKakao ? (
                <span className="inline-flex items-center gap-2 text-sm text-primary">
                  <CheckCircle2 className="size-4" aria-hidden />
                  연결됨
                </span>
              ) : (
                <Button disabled={pending} onClick={linkKakao} type="button">
                  {pending ? (
                    <Loader2 className="animate-spin" aria-hidden />
                  ) : (
                    <Link2 aria-hidden />
                  )}
                  카카오 계정 연결
                </Button>
              )}
            </div>
          </div>
        )}

        {message && (
          <p role="alert" className="mt-5 text-sm text-destructive">
            {message}
          </p>
        )}
      </section>

      <p className="mt-5 text-xs leading-relaxed text-muted-foreground">
        다른 맥락이 계정에 이미 연결된 카카오 계정은 자동으로 병합하지 않습니다. 소유자가 다른 두
        계정의 자료가 잘못 합쳐지는 것을 막기 위한 보호 정책입니다.
      </p>
      <Link
        href="/account/mcp"
        className="mt-6 inline-block text-sm text-primary underline-offset-4 hover:underline"
      >
        MCP 계정 연결 관리
      </Link>

      <section className="mt-10 rounded-xl border border-destructive/40 bg-card p-6">
        <h2 className="text-base font-semibold text-destructive">계정 탈퇴</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          연결된 로그인 방법, 모든 워크스페이스와 프로젝트, 회의록, 업로드 파일, API 키와 MCP 토큰이 영구 삭제됩니다.
          이 작업은 되돌릴 수 없습니다.
        </p>
        {!deleteOpen ? (
          <Button className="mt-5" variant="destructive" type="button" onClick={() => setDeleteOpen(true)}>
            계정 탈퇴
          </Button>
        ) : (
          <div className="mt-5 space-y-3">
            <label htmlFor="delete-account-confirm" className="block text-sm font-medium">
              확인하려면 ‘계정 탈퇴’를 입력하세요.
            </label>
            <input
              id="delete-account-confirm"
              autoComplete="off"
              value={deleteText}
              onChange={(event) => setDeleteText(event.target.value)}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            />
            {deleteError && <p role="alert" className="text-sm text-destructive">{deleteError}</p>}
            <div className="flex gap-2">
              <Button variant="destructive" type="button" disabled={deleteText !== "계정 탈퇴" || deleting} onClick={deleteAccount}>
                {deleting ? <Loader2 className="animate-spin" aria-hidden /> : null}
                영구 삭제
              </Button>
              <Button variant="outline" type="button" disabled={deleting} onClick={() => { setDeleteOpen(false); setDeleteText(""); setDeleteError(null); }}>
                취소
              </Button>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
