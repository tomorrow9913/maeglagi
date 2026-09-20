import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-lg flex-col items-center justify-center gap-4 px-5 text-center">
      <p className="text-xs font-semibold tracking-widest text-primary">404</p>
      <h1 className="text-lg font-semibold">찾을 수 없는 페이지입니다</h1>
      <p className="text-sm text-muted-foreground">주소가 바뀌었거나 삭제된 화면일 수 있습니다.</p>
      <div className="flex flex-wrap justify-center gap-2">
        <Link
          href="/workspaces"
          className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
        >
          워크스페이스로 가기
        </Link>
        <Link
          href="/"
          className="inline-flex h-9 items-center rounded-md border border-border px-4 text-sm font-medium transition-colors hover:bg-muted"
        >
          홈으로
        </Link>
      </div>
    </main>
  );
}
