"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

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
            options: { emailRedirectTo: `${location.origin}/auth/callback` },
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
    const next = new URLSearchParams(window.location.search).get("next");
    router.replace(next?.startsWith("/") && !next.startsWith("//") ? next : "/workspaces");
    router.refresh();
  }

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md items-center px-5">
      <section className="w-full rounded-2xl border border-border bg-card p-7">
        <p className="text-sm font-semibold text-primary">맥락이</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">
          {mode === "login" ? "로그인" : "계정 만들기"}
        </h1>
        <form className="mt-7 space-y-4" onSubmit={submit}>
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="이메일" required />
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="비밀번호" minLength={6} required />
          {message && <p className="text-sm text-muted-foreground">{message}</p>}
          <Button className="w-full" disabled={pending} type="submit">
            {pending ? "처리 중…" : mode === "login" ? "로그인" : "가입하기"}
          </Button>
        </form>
        <button className="mt-5 text-sm text-muted-foreground underline" onClick={() => setMode(mode === "login" ? "signup" : "login")}>
          {mode === "login" ? "처음이신가요? 계정 만들기" : "이미 계정이 있나요? 로그인"}
        </button>
      </section>
    </main>
  );
}
