"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createClient } from "@/lib/supabase/client";
import { isSupabaseConfigured } from "@/lib/supabase/config";

type Notice = { tone: "error" | "info"; text: string };

/** Supabase 오류 코드를 다음 행동이 보이는 문구로 바꿉니다. 영어 원문은 띄우지 않습니다. */
const authErrorMessages: Record<string, string> = {
  invalid_credentials: "이메일 또는 비밀번호가 맞지 않습니다.",
  email_not_confirmed: "메일 인증이 끝나지 않았습니다. 받은 메일의 링크를 열어 주세요.",
  user_already_exists: "이미 가입된 이메일입니다. 로그인해 주세요.",
  email_exists: "이미 가입된 이메일입니다. 로그인해 주세요.",
  weak_password: "비밀번호가 너무 짧거나 단순합니다. 6자 이상으로 바꿔 주세요.",
  email_address_invalid: "이메일 주소를 확인해 주세요.",
  over_email_send_rate_limit: "확인 메일을 너무 자주 요청했습니다. 조금 뒤에 다시 시도해 주세요.",
  over_request_rate_limit: "요청이 많아 잠시 멈췄습니다. 조금 뒤에 다시 시도해 주세요.",
  signup_disabled: "지금은 새 계정을 만들 수 없습니다.",
};

/** 다른 화면이 로그인으로 보낸 이유를 첫 화면에서 알려줍니다. */
function noticeFromQuery(params: URLSearchParams): Notice | null {
  if (params.get("error") === "callback")
    return {
      tone: "error",
      text: "인증 링크가 만료됐거나 이미 사용됐습니다. 다시 로그인하거나 계정을 만들어 주세요.",
    };
  if (params.get("reason") === "expired")
    return { tone: "info", text: "로그인이 만료됐습니다. 다시 로그인해 주세요." };
  return null;
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [pending, setPending] = useState(false);
  const [mailSent, setMailSent] = useState(false);

  useEffect(() => {
    setNotice(noticeFromQuery(new URLSearchParams(window.location.search)));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setNotice(null);
    try {
      const supabase = createClient();
      const result =
        mode === "login"
          ? await supabase.auth.signInWithPassword({ email, password })
          : await supabase.auth.signUp({
              email,
              password,
              options: { emailRedirectTo: `${location.origin}/auth/callback` },
            });
      if (result.error) {
        setNotice({
          tone: "error",
          text:
            authErrorMessages[result.error.code ?? ""] ??
            (mode === "login"
              ? "로그인하지 못했습니다. 잠시 후 다시 시도해 주세요."
              : "계정을 만들지 못했습니다. 잠시 후 다시 시도해 주세요."),
        });
        return;
      }
      if (mode === "signup" && !result.data.session) {
        setMailSent(true);
        return;
      }
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(next?.startsWith("/") && !next.startsWith("//") ? next : "/workspaces");
      router.refresh();
    } catch {
      setNotice({
        tone: "error",
        text: "서버에 연결하지 못했습니다. 인터넷 연결을 확인한 뒤 다시 시도해 주세요.",
      });
    } finally {
      setPending(false);
    }
  }

  function switchMode() {
    setMode(mode === "login" ? "signup" : "login");
    setNotice(null);
    setMailSent(false);
  }

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md items-center px-5">
      <section className="w-full rounded-2xl border border-border bg-card p-7">
        <Link href="/" className="text-sm font-semibold text-primary hover:underline">
          맥락이
        </Link>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">
          {mode === "login" ? "로그인" : "계정 만들기"}
        </h1>

        {!isSupabaseConfigured ? (
          <div className="mt-7 space-y-4 text-sm">
            <p role="status" className="text-muted-foreground">
              이 환경에는 로그인이 설정되어 있지 않습니다. 데모에서 맥락이를 둘러볼 수 있어요.
            </p>
            <Button asChild className="w-full">
              <Link href="/demo">데모 둘러보기</Link>
            </Button>
          </div>
        ) : mailSent ? (
          <div className="mt-7 space-y-4 text-sm">
            <p role="status">
              <span className="font-medium">{email}</span>로 확인 메일을 보냈습니다. 메일의 링크를
              열면 가입이 끝납니다.
            </p>
            <Button variant="outline" className="w-full" onClick={switchMode}>
              로그인으로 돌아가기
            </Button>
          </div>
        ) : (
          <>
            <form className="mt-7 space-y-4" onSubmit={submit}>
              <div className="space-y-1.5">
                <label htmlFor="login-email" className="text-sm font-medium">
                  이메일
                </label>
                <Input
                  id="login-email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@example.com"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="login-password" className="text-sm font-medium">
                  비밀번호
                </label>
                <Input
                  id="login-password"
                  name="password"
                  type="password"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  minLength={6}
                  aria-describedby={mode === "signup" ? "login-password-hint" : undefined}
                  required
                />
                {mode === "signup" ? (
                  <p id="login-password-hint" className="text-xs text-muted-foreground">
                    6자 이상으로 정해 주세요.
                  </p>
                ) : null}
              </div>
              {notice ? (
                <p
                  role={notice.tone === "error" ? "alert" : "status"}
                  className={
                    notice.tone === "error"
                      ? "text-sm text-destructive"
                      : "text-sm text-muted-foreground"
                  }
                >
                  {notice.text}
                </p>
              ) : null}
              <Button
                className="w-full"
                type="submit"
                pending={pending}
                pendingLabel={mode === "login" ? "로그인하는 중…" : "계정을 만드는 중…"}
              >
                {mode === "login" ? "로그인" : "계정 만들기"}
              </Button>
            </form>
            <button
              type="button"
              className="mt-5 text-sm text-muted-foreground underline"
              onClick={switchMode}
            >
              {mode === "login" ? "처음이신가요? 계정 만들기" : "이미 계정이 있나요? 로그인"}
            </button>
          </>
        )}
      </section>
    </main>
  );
}
