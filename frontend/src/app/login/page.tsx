"use client";

import { FormEvent, useEffect, useId, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Check, Circle, Eye, EyeOff, FileText, MailCheck } from "lucide-react";

import { MaeglagiMark, MaeglagiWordmark } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createClient } from "@/lib/supabase/client";
import { isSupabaseConfigured } from "@/lib/supabase/config";
import { cn } from "@/lib/utils";

type Mode = "login" | "signup";
type Notice = { tone: "error" | "info"; text: string };

const MIN_PASSWORD_LENGTH = 6;

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

const copy: Record<Mode, { title: string; description: string; submit: string; pending: string }> =
  {
    login: {
      title: "로그인",
      description: "워크스페이스로 돌아가 이어서 물어보세요.",
      submit: "로그인",
      pending: "로그인하는 중…",
    },
    signup: {
      title: "계정 만들기",
      description: "이메일 하나로 내 워크스페이스를 만들 수 있어요.",
      submit: "계정 만들기",
      pending: "계정을 만드는 중…",
    },
  };

export default function LoginPage() {
  const router = useRouter();
  const panelId = useId();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [mode, setMode] = useState<Mode>("login");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [pending, setPending] = useState(false);
  const [mailSent, setMailSent] = useState(false);
  const [resending, setResending] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("mode") === "signup") setMode("signup");
    setNotice(noticeFromQuery(params));
  }, []);

  const isSignup = mode === "signup";
  const longEnough = password.length >= MIN_PASSWORD_LENGTH;
  const matches = passwordConfirm.length > 0 && password === passwordConfirm;

  function switchMode(next: Mode) {
    if (next === mode) return;
    setMode(next);
    setNotice(null);
    setMailSent(false);
    setPasswordConfirm("");
    // 랜딩이나 메일에서 가입 화면으로 바로 올 수 있도록 주소에도 남깁니다. `next`는 유지합니다.
    const url = new URL(window.location.href);
    if (next === "signup") url.searchParams.set("mode", "signup");
    else url.searchParams.delete("mode");
    url.searchParams.delete("error");
    url.searchParams.delete("reason");
    window.history.replaceState(null, "", url);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    if (isSignup && !matches) {
      setNotice({ tone: "error", text: "비밀번호 확인이 일치하지 않습니다." });
      return;
    }
    setPending(true);
    setNotice(null);
    try {
      const supabase = createClient();
      const result = isSignup
        ? await supabase.auth.signUp({
            email,
            password,
            options: { emailRedirectTo: `${location.origin}/auth/callback` },
          })
        : await supabase.auth.signInWithPassword({ email, password });
      if (result.error) {
        setNotice({
          tone: "error",
          text:
            authErrorMessages[result.error.code ?? ""] ??
            (isSignup
              ? "계정을 만들지 못했습니다. 잠시 후 다시 시도해 주세요."
              : "로그인하지 못했습니다. 잠시 후 다시 시도해 주세요."),
        });
        return;
      }
      if (isSignup && !result.data.session) {
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

  async function resend() {
    if (resending) return;
    setResending(true);
    setNotice(null);
    try {
      const { error } = await createClient().auth.resend({
        type: "signup",
        email,
        options: { emailRedirectTo: `${location.origin}/auth/callback` },
      });
      setNotice(
        error
          ? {
              tone: "error",
              text:
                authErrorMessages[error.code ?? ""] ??
                "확인 메일을 다시 보내지 못했습니다. 잠시 후 다시 시도해 주세요.",
            }
          : { tone: "info", text: "확인 메일을 다시 보냈습니다." },
      );
    } catch {
      setNotice({ tone: "error", text: "확인 메일을 다시 보내지 못했습니다." });
    } finally {
      setResending(false);
    }
  }

  const noticeLine = notice ? (
    <p
      role={notice.tone === "error" ? "alert" : "status"}
      className={cn(
        "rounded-lg px-3 py-2 text-sm",
        notice.tone === "error"
          ? "bg-destructive/10 text-destructive"
          : "bg-muted text-muted-foreground",
      )}
    >
      {notice.text}
    </p>
  ) : null;

  return (
    <main className="grid min-h-dvh lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <BrandPanel mode={mode} />

      <section className="flex items-start justify-center px-5 py-10 sm:px-10 lg:pt-[16vh]">
        <div className="w-full max-w-sm">
          <Link href="/" aria-label="맥락이 홈" className="inline-flex lg:hidden">
            <MaeglagiWordmark className="text-lg" />
          </Link>

          {!isSupabaseConfigured ? (
            <div className="mt-8 space-y-4 lg:mt-0">
              <h1 className="text-2xl font-semibold tracking-tight">로그인</h1>
              <p role="status" className="text-sm leading-relaxed text-muted-foreground">
                이 환경에는 로그인이 설정되어 있지 않습니다. 데모에서 맥락이를 둘러볼 수 있어요.
              </p>
              <Button asChild className="h-10 w-full">
                <Link href="/demo">데모 둘러보기</Link>
              </Button>
            </div>
          ) : mailSent ? (
            <div className="mt-8 space-y-5 lg:mt-0">
              <span className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
                <MailCheck className="size-6" aria-hidden />
              </span>
              <div className="space-y-2">
                <h1 className="text-2xl font-semibold tracking-tight">메일함을 확인해 주세요</h1>
                <p role="status" className="text-sm leading-relaxed text-muted-foreground">
                  <span className="font-medium break-all text-foreground">{email}</span>로 확인
                  메일을 보냈습니다. 메일의 링크를 열면 가입이 끝납니다.
                </p>
              </div>
              {noticeLine}
              <div className="space-y-2">
                <Button className="h-10 w-full" onClick={() => switchMode("login")}>
                  로그인으로 돌아가기
                </Button>
                <Button
                  variant="ghost"
                  className="h-10 w-full text-muted-foreground"
                  pending={resending}
                  pendingLabel="다시 보내는 중…"
                  onClick={resend}
                >
                  메일이 오지 않았다면 다시 보내기
                </Button>
              </div>
            </div>
          ) : (
            <>
              {/* 두 화면이 같은 폼처럼 보이지 않도록, 어느 쪽에 있는지를 탭으로 먼저 보여줍니다. */}
              <div
                role="tablist"
                aria-label="로그인 또는 계정 만들기"
                className="mt-8 grid grid-cols-2 rounded-xl bg-muted p-1 lg:mt-0"
              >
                {(["login", "signup"] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    role="tab"
                    aria-selected={mode === value}
                    aria-controls={panelId}
                    onClick={() => switchMode(value)}
                    className={cn(
                      "h-9 rounded-lg text-sm font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                      mode === value
                        ? "bg-card text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {copy[value].title}
                  </button>
                ))}
              </div>

              <div id={panelId} role="tabpanel" className="mt-8">
                <h1 className="text-2xl font-semibold tracking-tight">{copy[mode].title}</h1>
                <p className="mt-1.5 text-sm text-muted-foreground">{copy[mode].description}</p>

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
                      className="h-10 bg-card"
                      required
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label htmlFor="login-password" className="text-sm font-medium">
                      비밀번호
                    </label>
                    <div className="relative">
                      <Input
                        id="login-password"
                        name="password"
                        type={showPassword ? "text" : "password"}
                        autoComplete={isSignup ? "new-password" : "current-password"}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        minLength={MIN_PASSWORD_LENGTH}
                        aria-describedby={isSignup ? "login-password-rules" : undefined}
                        className="h-10 bg-card pr-10"
                        required
                      />
                      <button
                        type="button"
                        aria-label={showPassword ? "비밀번호 가리기" : "비밀번호 보기"}
                        aria-pressed={showPassword}
                        onClick={() => setShowPassword((shown) => !shown)}
                        className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-lg text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
                      >
                        {showPassword ? (
                          <EyeOff className="size-4" aria-hidden />
                        ) : (
                          <Eye className="size-4" aria-hidden />
                        )}
                      </button>
                    </div>
                  </div>

                  {isSignup ? (
                    <>
                      <div className="space-y-1.5">
                        <label htmlFor="login-password-confirm" className="text-sm font-medium">
                          비밀번호 확인
                        </label>
                        <Input
                          id="login-password-confirm"
                          name="password-confirm"
                          type={showPassword ? "text" : "password"}
                          autoComplete="new-password"
                          value={passwordConfirm}
                          onChange={(e) => setPasswordConfirm(e.target.value)}
                          aria-describedby="login-password-rules"
                          aria-invalid={passwordConfirm.length > 0 && !matches ? true : undefined}
                          className="h-10 bg-card"
                          required
                        />
                      </div>
                      <ul id="login-password-rules" className="space-y-1 text-xs">
                        <Rule met={longEnough}>{MIN_PASSWORD_LENGTH}자 이상</Rule>
                        <Rule met={matches}>비밀번호 확인과 일치</Rule>
                      </ul>
                    </>
                  ) : null}

                  {noticeLine}

                  <Button
                    className="h-10 w-full"
                    type="submit"
                    pending={pending}
                    pendingLabel={copy[mode].pending}
                  >
                    {copy[mode].submit}
                    <ArrowRight aria-hidden />
                  </Button>

                  {isSignup ? (
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      계정을 만들면 확인 메일을 보냅니다. 메일의 링크를 열면 가입이 끝납니다.
                    </p>
                  ) : null}
                </form>
              </div>

              <div className="mt-8 flex items-center gap-3 text-xs text-muted-foreground">
                <span className="h-px flex-1 bg-border" aria-hidden />
                계정 없이 먼저 보고 싶다면
                <span className="h-px flex-1 bg-border" aria-hidden />
              </div>
              <Button asChild variant="outline" className="mt-4 h-10 w-full">
                <Link href="/demo">예시 워크스페이스 둘러보기</Link>
              </Button>
            </>
          )}
        </div>
      </section>
    </main>
  );
}

/** 비밀번호 조건을 입력하는 동안 바로 확인해 줍니다. 색만으로 구분하지 않도록 아이콘과 문구를 함께 씁니다. */
function Rule({ met, children }: { met: boolean; children: React.ReactNode }) {
  return (
    <li className={cn("flex items-center gap-1.5", met ? "text-success" : "text-muted-foreground")}>
      {met ? <Check className="size-3.5" aria-hidden /> : <Circle className="size-3.5" aria-hidden />}
      <span>{children}</span>
      <span className="sr-only">{met ? "충족" : "미충족"}</span>
    </li>
  );
}

const signupSteps = [
  { title: "계정 만들기", description: "이메일과 비밀번호만 정하면 됩니다." },
  {
    title: "워크스페이스 만들고 AI 연결하기",
    description: "API key나 Ollama 서버, 또는 쓰던 에이전트를 MCP로 연결해요.",
  },
  { title: "회의와 문서를 올리고 물어보기", description: "결정과 그 이유를 근거와 함께 답해요." },
];

/**
 * 넓은 화면에서만 보이는 브랜드 면.
 *
 * 로그인은 "돌아오면 무엇을 할 수 있는지"(답변 예시), 가입은 "가입하면 어떤 순서로 시작하는지"
 * (세 단계)를 보여줘 두 화면의 목적이 한눈에 갈리게 합니다. 색은 브랜드 면 위 규칙
 * (docs/brand.md 2절: 심볼은 `text-card`)을 따릅니다.
 */
function BrandPanel({ mode }: { mode: Mode }) {
  return (
    <aside className="relative hidden flex-col justify-between overflow-hidden bg-primary p-10 text-primary-foreground lg:flex xl:p-14">
      <MaeglagiMark className="pointer-events-none absolute -right-16 -bottom-20 size-96 text-primary-foreground/10" />

      <Link
        href="/"
        aria-label="맥락이 홈"
        className="relative inline-flex w-fit items-center gap-1.5 text-lg font-semibold tracking-tight"
      >
        <MaeglagiMark className="size-[1.15em] text-card" />
        맥락이
      </Link>

      <div className="relative max-w-md">
        {mode === "login" ? (
          <>
            <h2 className="text-3xl leading-snug font-semibold tracking-tight break-keep">
              지난 회의에서 왜 그렇게 정했는지, 근거와 함께 답해요.
            </h2>
            <figure className="mt-8 space-y-3 text-sm">
              <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-primary-foreground/15 px-4 py-2.5">
                하이브리드 검색은 왜 쓰기로 했나요?
              </p>
              <div className="max-w-[92%] rounded-2xl rounded-bl-md bg-card px-4 py-3 text-card-foreground">
                <p className="leading-relaxed">
                  벡터 검색만으로는 관련 청크를 놓치는 사례가 있어, 그래프 이웃을 더한 hybrid
                  retrieval을 채택했습니다
                  <sup className="ml-0.5 font-medium text-primary">[1]</sup>.
                </p>
                <p className="mt-2.5 inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
                  <FileText className="size-3" aria-hidden />
                  9/11 기술 검토 회의
                </p>
              </div>
              <figcaption className="sr-only">맥락이 답변 예시</figcaption>
            </figure>
          </>
        ) : (
          <>
            <h2 className="text-3xl leading-snug font-semibold tracking-tight break-keep">
              흩어진 회의와 문서를 하나의 맥락으로 이어 보세요.
            </h2>
            <ol className="mt-8 space-y-5">
              {signupSteps.map((step, index) => (
                <li key={step.title} className="flex gap-4">
                  <span
                    aria-hidden
                    className={cn(
                      "flex size-7 shrink-0 items-center justify-center rounded-full text-sm font-semibold",
                      index === 0
                        ? "bg-card text-primary"
                        : "border border-primary-foreground/40 text-primary-foreground",
                    )}
                  >
                    {index + 1}
                  </span>
                  <div>
                    <p className="text-sm font-semibold">
                      {step.title}
                      {index === 0 ? (
                        <span className="ml-2 rounded-full bg-primary-foreground/15 px-2 py-0.5 text-xs font-medium">
                          지금 단계
                        </span>
                      ) : null}
                    </p>
                    <p className="mt-0.5 text-sm text-primary-foreground/80">{step.description}</p>
                  </div>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>

      <p className="relative text-sm text-primary-foreground/80">흩어진 업무의 맥락을 잇다.</p>
    </aside>
  );
}
