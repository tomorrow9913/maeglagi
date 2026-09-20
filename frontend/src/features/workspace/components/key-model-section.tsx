"use client";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { ModelOption, ModelRole, ModelSelections, RoleModels } from "@/lib/api";
import { toUserMessage } from "@/lib/api/error-message";

import { ModelPicker } from "./model-picker";

/**
 * 키를 확인한 뒤 나타나는 "사용할 모델" 영역입니다.
 *
 * 공급자를 고르는 순간 선택 방식을 보여주고, 키가 확인되면 추천 선택을 드러냅니다.
 */
export function KeyModelSection({
  idPrefix,
  hasValidKey,
  roles,
  selections,
  onSelect,
  isLoading,
  error,
  onRetry,
  isOllama = false,
  disabled = false,
}: {
  idPrefix: string;
  hasValidKey: boolean;
  roles: RoleModels[] | undefined;
  selections: ModelSelections;
  onSelect: (role: ModelRole, option: ModelOption) => void;
  isLoading: boolean;
  error: Error | undefined;
  onRetry: () => void;
  /** Ollama는 모델을 하나씩 점검해 목록이 늦게 옵니다. 기다리는 이유를 알려줍니다. */
  isOllama?: boolean;
  disabled?: boolean;
}) {
  const reason = error ? toUserMessage(error, "") : "";

  return (
    <div className="space-y-3 border-t border-border pt-4">
      <div>
        <h3 className="text-sm font-medium">사용할 모델</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          가격이 낮은 모델부터 보여주고, 추천 모델을 미리 골라 두었어요. 가격을 알 수 없는 모델은
          뒤에 나옵니다.
        </p>
      </div>

      {!hasValidKey ? (
        <p className="text-xs text-muted-foreground">
          AI 연결을 확인하면 용도별 추천 모델과 다른 선택지를 보여줍니다.
        </p>
      ) : isLoading ? (
        <p role="status" className="flex items-start gap-2 text-xs text-muted-foreground">
          <Spinner className="mt-0.5 size-3" />
          {isOllama
            ? "Ollama 서버의 모델을 하나씩 확인하고 있어요. 모델이 많으면 오래 걸려요."
            : "쓸 수 있는 모델을 불러오고 있어요"}
        </p>
      ) : error ? (
        <div role="alert" className="space-y-2 text-xs">
          <p className="text-destructive">모델 목록을 불러오지 못했습니다.</p>
          {reason ? <p className="text-muted-foreground">{reason}</p> : null}
          <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={onRetry}>
            다시 시도
          </Button>
        </div>
      ) : roles ? (
        <ModelPicker
          idPrefix={idPrefix}
          roles={roles}
          value={selections}
          onChange={onSelect}
          disabled={disabled}
          includesOllama={isOllama}
        />
      ) : null}
    </div>
  );
}
