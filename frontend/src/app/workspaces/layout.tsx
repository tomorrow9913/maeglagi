import type { ReactNode } from "react";

import { AppHeader } from "@/components/layout/app-header";
import { DemoBanner } from "@/components/layout/demo-banner";

export default function WorkspacesLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <DemoBanner />
      <AppHeader />
      {children}
    </div>
  );
}
