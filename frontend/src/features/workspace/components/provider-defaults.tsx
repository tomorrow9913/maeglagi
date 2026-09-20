import type { AiProvider, ModelRole } from "@/lib/api";
import { cn } from "@/lib/utils";

import { modelRoleInfo } from "../lib/model-roles";

const roleOrder: ModelRole[] = ["answer", "extraction", "embedding", "transcription"];

/**
 * 공급자를 고르는 즉시 보여주는 기본 모델입니다. 키를 넣기 전이라 실제로 쓸 수 있는지는 아직
 * 모르므로 "쓸 수 있다/없다"는 말하지 않고, 기본값이 있는 용도만 나열합니다. 키를 확인하면
 * 이 키가 제공하는 모델 안에서 이 값이 미리 선택됩니다.
 */
export function ProviderDefaults({
  provider,
  className,
}: {
  provider: AiProvider | undefined;
  className?: string;
}) {
  const defaults = provider?.defaultModels ?? {};
  const roles = roleOrder.filter((role) => defaults[role]);
  if (!provider || roles.length === 0) return null;

  return (
    <div className={cn("space-y-1", className)}>
      <p className="text-xs text-muted-foreground">
        {provider.displayName}의 기본 모델입니다. 연결을 확인하면 이 연결로 쓸 수 있는 모델 중에서
        바꿀 수 있어요.
      </p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        {roles.map((role) => (
          <div key={role} className="contents">
            <dt className="text-muted-foreground">{modelRoleInfo[role].label}</dt>
            <dd className="font-mono">{defaults[role]}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
