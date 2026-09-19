"use client";

import { TriangleAlert } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ModelOption, ModelRole, ModelSelections, RoleModels } from "@/lib/api";

import { modelRoleInfo, optionKey } from "../lib/model-roles";

/**
 * 용도별로 쓸 모델을 고릅니다.
 *
 * 되고 안 되는 것은 provider가 아니라 그 키로 쓸 수 있는 모델에 달려 있어서, 고를 모델이
 * 하나도 없는 용도만 무엇이 안 되는지 알려줍니다. 옵션에 공급자가 여럿 섞여 있으면
 * 모델 이름 앞에 공급자를 함께 보여줍니다.
 */
export function ModelPicker({
  idPrefix,
  roles,
  value,
  onChange,
  disabled = false,
}: {
  idPrefix: string;
  roles: RoleModels[];
  value: ModelSelections;
  onChange: (role: ModelRole, option: ModelOption) => void;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-4">
      {roles.map((entry) => {
        const info = modelRoleInfo[entry.role];
        const id = `${idPrefix}-${entry.role}`;
        const selected = value[entry.role];
        const hasMultipleProviders = new Set(entry.options.map((o) => o.provider)).size > 1;

        return (
          <div key={entry.role} className="space-y-1.5">
            <label htmlFor={id} className="text-sm font-medium">
              {info.label}
            </label>

            {entry.options.length === 0 ? (
              <p className="flex items-start gap-1.5 text-xs text-warning">
                <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
                <span>
                  이 키로 쓸 수 있는 {info.label} 모델이 없어 {info.unavailable}
                </span>
              </p>
            ) : (
              <>
                <Select
                  value={selected ? optionKey(selected) : undefined}
                  onValueChange={(key) => {
                    const option = entry.options.find((o) => optionKey(o) === key);
                    if (option) onChange(entry.role, option);
                  }}
                >
                  <SelectTrigger id={id} disabled={disabled || entry.locked} className="w-full">
                    <SelectValue placeholder="모델을 고르세요" />
                  </SelectTrigger>
                  <SelectContent>
                    {entry.options.map((option) => (
                      <SelectItem key={optionKey(option)} value={optionKey(option)}>
                        {hasMultipleProviders
                          ? `${option.provider} · ${option.model}`
                          : option.model}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {info.description}
                  {info.fixedNote ? (
                    <span className={entry.locked ? "block" : "block text-warning"}>
                      {entry.locked
                        ? `정해진 모델이라 바꿀 수 없습니다. ${info.fixedNote}`
                        : `한 번 정하면 바꿀 수 없습니다. ${info.fixedNote}`}
                    </span>
                  ) : null}
                </p>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
