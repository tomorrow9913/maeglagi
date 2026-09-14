import type { ReactNode } from "react";

import { AppHeader } from "@/components/layout/app-header";

export default function WorkspacesLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader />
      {children}
    </div>
  );
}
