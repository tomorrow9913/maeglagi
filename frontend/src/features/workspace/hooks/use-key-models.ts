"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { LlmProvider, ModelOption, ModelRole, ModelSelections, RoleModels } from "@/lib/api";

import { initialSelections } from "../lib/model-roles";

/**
 * 검증을 통과한 키로 쓸 수 있는 모델을 받아 용도별 선택 상태를 만듭니다.
 *
 * `validatedKey`가 없으면(입력 중이거나 검증 실패) 아무것도 요청하지 않고 목록을 비웁니다.
 * provider나 키가 바뀌면 목록을 다시 받고 선택은 첫 옵션으로 초기화합니다.
 */
export function useKeyModels(
  provider: LlmProvider,
  validatedKey: string | undefined,
  defaults: Partial<Record<ModelRole, string>> | undefined,
) {
  const [roles, setRoles] = useState<RoleModels[]>();
  const [error, setError] = useState<Error>();
  const [isLoading, setIsLoading] = useState(false);
  const [selections, setSelections] = useState<ModelSelections>({});
  // 기본 모델은 선택을 미리 고를 때만 읽습니다. 값이 바뀌어도 목록을 다시 받을 이유는 없으므로
  // 의존성이 아니라 ref로 둡니다.
  const defaultsRef = useRef(defaults);
  defaultsRef.current = defaults;

  useEffect(() => {
    setRoles(undefined);
    setError(undefined);
    setSelections({});
    if (!validatedKey) {
      setIsLoading(false);
      return;
    }

    const controller = new AbortController();
    setIsLoading(true);
    api
      .listKeyModels({ provider, apiKey: validatedKey }, controller.signal)
      .then((models) => {
        if (controller.signal.aborted) return;
        setRoles(models.roles);
        setSelections(initialSelections(models.roles, { [provider]: defaultsRef.current }));
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause : new Error(String(cause)));
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });

    return () => controller.abort();
  }, [provider, validatedKey]);

  const select = useCallback((role: ModelRole, option: ModelOption) => {
    setSelections((current) => ({ ...current, [role]: option }));
  }, []);

  return { roles, selections, select, isLoading, error };
}
