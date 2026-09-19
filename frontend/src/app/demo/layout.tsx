import type { ReactNode } from "react";

import { DemoApiProvider } from "@/lib/api/context";
import { DemoShell } from "./demo-shell";

export default function DemoLayout({ children }: { children: ReactNode }) {
  return (
    <DemoApiProvider><DemoShell>{children}</DemoShell></DemoApiProvider>
  );
}
