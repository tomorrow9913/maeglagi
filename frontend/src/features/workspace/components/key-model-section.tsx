"use client";

import { Loader2 } from "lucide-react";

import type { ModelOption, ModelRole, ModelSelections, RoleModels } from "@/lib/api";

import { ModelPicker } from "./model-picker";

/**
 * 키를 확인한 뒤 나타나는 "사용할 모델" 영역입니다.
 *
 * 키가 아직 확인되지 않았으면 아무것도 그리지 않습니다. 목록을 받지 못해도 생성은 막지 않고
 * 서버가 정한 기본 모델을 쓰게 두므로, 오류는 안내만 합니다.
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
  if (!hasValidKey) return null;

  return (
    <div className="space-y-3 border-t border-border pt-4">
      <div>
        <h3 className="text-sm font-medium">사용할 모델</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          이 키로 쓸 수 있는 모델입니다. 용도마다 골라 주세요.
        </p>
      </div>

      {isLoading ? (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" aria-hidden />쓸 수 있는 모델을 불러오는 중…
        </p>
      ) : error ? (
        <p className="text-xs text-destructive">
          모델 목록을 불러오지 못했습니다. 지금 만들면 서버가 정한 기본 모델을 씁니다.
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
