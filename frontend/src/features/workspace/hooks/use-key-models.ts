"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useApi } from "@/lib/api/context";
import type { LlmProvider, ModelOption, ModelRole, ModelSelections, RoleModels } from "@/lib/api";

import { initialSelections } from "../lib/model-roles";

/**
 * 검증을 통과한 키로 쓸 수 있는 모델을 받아 용도별 선택 상태를 만듭니다.
 *
 * 검증된 새 키나 저장된 계정 연결의 ID로 모델을 조회합니다. 입력이나 연결이 바뀐
 * 렌더에서는 이전 응답을 즉시 숨겨, effect가 실행되기 전에도 오래된 선택을 제출하지 않습니다.
 */
export function useKeyModels(
  provider: LlmProvider,
  validatedKey: string | undefined,
  defaults: Partial<Record<ModelRole, string>> | undefined,
  baseUrl?: string,
  credentialId?: string,
) {
  const api = useApi();
  const [roles, setRoles] = useState<RoleModels[]>();
  const [error, setError] = useState<Error>();
  const [isLoading, setIsLoading] = useState(false);
  const [selections, setSelections] = useState<ModelSelections>({});
  const [resolvedIdentity, setResolvedIdentity] = useState<string>();
  // 실패한 뒤 같은 연결로 다시 받아 올 때 올립니다.
  const [attempt, setAttempt] = useState(0);
  const identity = JSON.stringify([provider, validatedKey ?? null, baseUrl?.trim() ?? null, credentialId ?? null]);
  const canLoad = validatedKey !== undefined || Boolean(credentialId);
  // 기본 모델은 선택을 미리 고를 때만 읽습니다. 값이 바뀌어도 목록을 다시 받을 이유는 없으므로
  // 의존성이 아니라 ref로 둡니다.
  const defaultsRef = useRef(defaults);
  defaultsRef.current = defaults;

  useEffect(() => {
    setRoles(undefined);
    setError(undefined);
    setSelections({});
    setResolvedIdentity(undefined);
    if (!canLoad) {
      setIsLoading(false);
      return;
    }

    const controller = new AbortController();
    setIsLoading(true);
    api
      .listKeyModels({ provider, ...(credentialId ? { credentialId } : { apiKey: validatedKey }), ...(baseUrl ? { baseUrl: baseUrl.trim() } : {}) }, controller.signal)
      .then((models) => {
        if (controller.signal.aborted) return;
        setRoles(models.roles);
        setSelections(initialSelections(models.roles, { [provider]: defaultsRef.current }));
        setResolvedIdentity(identity);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause : new Error(String(cause)));
        setResolvedIdentity(identity);
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });

    return () => controller.abort();
  }, [provider, validatedKey, baseUrl, credentialId, api, canLoad, identity, attempt]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);

  const select = useCallback((role: ModelRole, option: ModelOption) => {
    setSelections((current) => ({ ...current, [role]: option }));
  }, []);

  const isCurrent = resolvedIdentity === identity;
  return {
    roles: isCurrent ? roles : undefined,
    selections: isCurrent ? selections : {},
    select,
    isLoading: canLoad && (!isCurrent || isLoading),
    error: isCurrent ? error : undefined,
    reload,
  };
}
