"use client";

import { useCallback, useEffect, useState } from "react";

export type AsyncState<T> = {
  data: T | undefined;
  error: Error | undefined;
  isLoading: boolean;
  reload: () => void;
};

/**
 * API 호출 한 건의 로딩·에러·재시도 상태를 다룹니다.
 *
 * 화면이 언마운트되거나 deps가 바뀌면 이전 요청을 abort 하므로, 늦게 도착한
 * 응답이 새 상태를 덮어쓰지 않습니다.
 *
 * `fn`은 매 렌더마다 새로 만들어지기 쉬우므로 deps로만 재실행을 판단합니다.
 */
export function useAsync<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  deps: unknown[] = [],
): AsyncState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [isLoading, setIsLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setError(undefined);

    fn(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setData(result);
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
  }, [...deps, nonce]);

  return { data, error, isLoading, reload };
}
