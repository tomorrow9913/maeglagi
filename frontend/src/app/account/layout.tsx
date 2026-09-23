import type { ReactNode } from "react";
import Link from "next/link";

import { AppHeader } from "@/components/layout/app-header";

export default function AccountLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader />
      <nav className="border-b border-border/60" aria-label="계정 설정">
        <div className="mx-auto flex w-full max-w-4xl gap-5 px-5 py-3 text-sm">
          <Link href="/account/ai" className="text-muted-foreground hover:text-foreground">
            AI 연결
          </Link>
          <Link href="/account/mcp" className="text-muted-foreground hover:text-foreground">
            MCP
          </Link>
          <Link href="/account/security" className="text-muted-foreground hover:text-foreground">
            보안
          </Link>
        </div>
      </nav>
      {children}
    </div>
  );
}
