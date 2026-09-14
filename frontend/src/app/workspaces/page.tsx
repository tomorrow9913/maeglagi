import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/layout/page-header";
import { workspacePath } from "@/lib/navigation";

export const metadata: Metadata = {
  title: "워크스페이스 | 맥락이",
};

// TODO(Day 2): API 클라이언트로 실제 목록을 불러오고 생성 폼을 붙입니다.
const placeholderWorkspaces = [{ id: "demo", name: "데모 워크스페이스", sourceCount: 0 }];

export default function WorkspacesPage() {
  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-10">
      <PageHeader title="워크스페이스" description="맥락을 모을 공간을 고르거나 새로 만듭니다." />
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {placeholderWorkspaces.map((workspace) => (
          <li key={workspace.id}>
            <Link
              href={workspacePath(workspace.id)}
              className="block rounded-xl border border-border p-5 transition-colors hover:border-foreground/30"
            >
              <p className="font-medium">{workspace.name}</p>
              <p className="mt-1 text-sm text-muted-foreground">소스 {workspace.sourceCount}개</p>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
