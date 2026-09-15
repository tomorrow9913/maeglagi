import Link from "next/link";

export function AppHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-border/60 bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-6 px-5">
        <Link href="/" className="text-sm font-semibold tracking-tight">
          맥락이
        </Link>
        <Link
          href="/workspaces"
          className="text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          워크스페이스
        </Link>
      </div>
    </header>
  );
}
