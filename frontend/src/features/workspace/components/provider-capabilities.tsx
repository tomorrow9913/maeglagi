import { Check, TriangleAlert } from "lucide-react";

import { PROVIDER_FEATURES } from "@/lib/api/providers";
import type { AiProvider } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * 고른 provider로 무엇이 되고 안 되는지 보여줍니다.
 *
 * 지원하지 않는 기능은 키 등록 뒤에 조용히 빠지지 않도록 등록 전에 알려줍니다.
 */
export function ProviderCapabilities({
  provider,
  className,
}: {
  provider: AiProvider | undefined;
  className?: string;
}) {
  if (!provider) return null;

  return (
    <ul
      className={cn("space-y-1 text-xs", className)}
      aria-label={`${provider.displayName} 지원 기능`}
    >
      {PROVIDER_FEATURES.map((feature) => {
        const supported = provider.capabilities.includes(feature.capability);
        return (
          <li
            key={feature.capability}
            className={cn(
              "flex items-start gap-1.5",
              supported ? "text-muted-foreground" : "text-warning",
            )}
          >
            {supported ? (
              <Check className="mt-0.5 size-3 shrink-0 text-success" aria-hidden />
            ) : (
              <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
            )}
            <span>
              {supported ? feature.label : `${feature.label} 불가 — ${feature.unsupported}`}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
