"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createClient } from "@/lib/supabase/client";
import { authCallbackUrl, kakaoOAuthOptions, safeNextPath } from "@/lib/auth-redirect";
import { isKakaoOAuthAvailable } from "@/lib/kakao-availability";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [callbackFailed, setCallbackFailed] = useState(false);

  useEffect(() => {
    setCallbackFailed(new URLSearchParams(window.location.search).get("error") === "callback");
  }, []);

  function nextPath() {
    return safeNextPath(new URLSearchParams(window.location.search).get("next"));
  }

  async function signInWithKakao() {
    setPending(true);
    setMessage(null);
    const { error } = await createClient().auth.signInWithOAuth(
      kakaoOAuthOptions(window.location.origin, nextPath()),
    );
    if (error) {
      setMessage(error.message);
      setPending(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setMessage(null);
    const supabase = createClient();
    const result =
      mode === "login"
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({
            email,
            password,
            options: { emailRedirectTo: authCallbackUrl(window.location.origin, nextPath()) },
          });
    setPending(false);
    if (result.error) {
      setMessage(result.error.message);
      return;
    }
    if (mode === "signup" && !result.data.session) {
      setMessage("확인 메일을 보냈습니다. 메일의 링크를 열어주세요.");
      return;
    }
    router.replace(nextPath());
    router.refresh();
  }

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md items-center px-5">
      <section className="w-full rounded-2xl border border-border bg-card p-7">
        <p className="text-sm font-semibold text-primary">맥락이</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">
          {mode === "login" ? "로그인" : "계정 만들기"}
        </h1>
        {callbackFailed && !message && (
          <p role="alert" className="mt-5 text-sm text-destructive">
            로그인을 완료하지 못했습니다. 다시 시도해 주세요.
          </p>
        )}
        <form className="mt-7 space-y-4" onSubmit={submit}>
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="이메일"
            required
          />
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="비밀번호"
            minLength={6}
            required
          />
          {message && <p className="text-sm text-muted-foreground">{message}</p>}
          <Button className="w-full" disabled={pending} type="submit">
            {pending ? "처리 중…" : mode === "login" ? "로그인" : "가입하기"}
          </Button>
        </form>
        {isKakaoOAuthAvailable && (
          <>
            <div className="my-5 flex items-center gap-3 text-xs text-muted-foreground">
              <span className="h-px flex-1 bg-border" />
              또는
              <span className="h-px flex-1 bg-border" />
            </div>
            <Button
              className="w-full bg-[#FEE500] text-[#191919] hover:bg-[#F5DC00]"
              disabled={pending}
              onClick={signInWithKakao}
              type="button"
            >
              카카오로 계속하기
            </Button>
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
              이미 이메일로 가입했다면 이메일로 먼저 로그인한 뒤, 계정 보안에서 카카오를 연결해
              주세요. 기존 자료를 같은 계정에서 이용할 수 있습니다.
            </p>
          </>
        )}
        <button
          className="mt-5 text-sm text-muted-foreground underline"
          onClick={() => setMode(mode === "login" ? "signup" : "login")}
        >
          {mode === "login" ? "처음이신가요? 계정 만들기" : "이미 계정이 있나요? 로그인"}
        </button>
      </section>
    </main>
  );
}
