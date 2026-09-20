"use client";

import { useCallback, useEffect, useState } from "react";

export type AsyncState<T> = {
  data: T | undefined;
  error: Error | undefined;
  /** 요청이 진행 중인지. 첫 로드와 재조회를 모두 포함합니다. */
  isLoading: boolean;
  /** 이미 보여줄 data가 있는 상태에서 다시 가져오는 중인지 */
  isRefetching: boolean;
  reload: () => void;
};

/**
 * API 호출 한 건의 로딩·에러·재시도 상태를 다룹니다.
 *
 * 화면이 언마운트되거나 deps가 바뀌면 이전 요청을 abort 하므로, 늦게 도착한
 * 응답이 새 상태를 덮어쓰지 않습니다.
 *
 * `fn`은 매 렌더마다 새로 만들어지기 쉬우므로 deps로만 재실행을 판단합니다.
 *
 * 재조회 중에도 이전 `data`를 유지합니다. 필터처럼 같은 목록을 다시 받는 화면은
 * `isLoading && !data`일 때만 스켈레톤을 쓰고, `isRefetching`이면 기존 내용을 흐리게 둡니다.
 * 워크스페이스처럼 대상 자체가 바뀌면 이전 내용이 남으면 안 되므로 `resetKey`를 넘깁니다.
 */
export function useAsync<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  deps: unknown[] = [],
  options: { resetKey?: unknown } = {},
): AsyncState<T> {
  const { resetKey } = options;
  // 어떤 대상의 결과인지 함께 기억해, 대상이 바뀐 첫 렌더부터 이전 내용을 숨깁니다.
  const [result, setResult] = useState<{ value: T; key: unknown }>();
  const [error, setError] = useState<Error>();
  const [isLoading, setIsLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const data = result && Object.is(result.key, resetKey) ? result.value : undefined;

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setError(undefined);

    fn(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setResult({ value, key: resetKey });
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause : new Error(String(cause)));
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });

    return () => controller.abort();
    /*
     * `fn`을 의존성에서 일부러 뺍니다. 호출부가 인라인 화살표 함수를 넘기는
     * 경우가 대부분이라 매 렌더마다 새 함수가 되고, 그대로 두면 요청이
     * 무한히 반복됩니다. 재실행 시점은 호출부가 deps로 결정합니다.
     */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, resetKey]);

  return { data, error, isLoading, isRefetching: isLoading && data !== undefined, reload };
}
