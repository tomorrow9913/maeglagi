"use client";

import { Loader2 } from "lucide-react";

import type { ModelOption, ModelRole, ModelSelections, RoleModels } from "@/lib/api";

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
  disabled = false,
}: {
  idPrefix: string;
  hasValidKey: boolean;
  roles: RoleModels[] | undefined;
  selections: ModelSelections;
  onSelect: (role: ModelRole, option: ModelOption) => void;
  isLoading: boolean;
  error: Error | undefined;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-3 border-t border-border pt-4">
      <div>
        <h3 className="text-sm font-medium">사용할 모델</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          키로 확인된 모델 중 가격 정보가 있는 것은 낮은 순서로 보여줍니다.
          가격을 확인할 수 없는 모델은 뒤에 표시됩니다. 추천값도 아래에서 직접 확인하세요.
        </p>
      </div>

      {!hasValidKey ? (
        <p className="text-xs text-muted-foreground">
          선택한 공급자의 키를 검증하면 용도별 추천 모델과 다른 선택지를 보여줍니다.
        </p>
      ) : isLoading ? (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" aria-hidden />쓸 수 있는 모델을 불러오는 중…
        </p>
      ) : error ? (
        <p className="text-xs text-destructive">
          모델 목록을 불러오지 못했습니다. 목록을 확인한 뒤 다시 시도해 주세요.
          <span className="mt-0.5 block text-muted-foreground">{error.message}</span>
        </p>
      ) : roles ? (
        <ModelPicker
          idPrefix={idPrefix}
          roles={roles}
          value={selections}
          onChange={onSelect}
          disabled={disabled}
        />
      ) : null}
    </div>
  );
}
