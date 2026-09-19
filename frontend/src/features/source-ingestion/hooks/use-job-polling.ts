"use client";

import { useEffect, useRef, useState } from "react";

import { useApi } from "@/lib/api/context";
import type { ProcessingJob } from "@/lib/api";

const POLL_INTERVAL_MS = 1_000;

function isTerminal(job: ProcessingJob): boolean {
  return job.status === "succeeded" || job.status === "failed";
}

/**
 * 진행 중인 처리 작업들의 상태를 주기적으로 조회합니다.
 *
 * 끝난 작업은 폴링에서 빠지고, 하나가 끝날 때마다 `onSettled`가 한 번
 * 호출됩니다. 화면이 사라지면 진행 중이던 요청을 abort 합니다.
 */
export function useJobPolling(
  jobIds: string[],
  onSettled?: (job: ProcessingJob) => void,
): Record<string, ProcessingJob> {
  const [jobs, setJobs] = useState<Record<string, ProcessingJob>>({});
  const api = useApi();

  // 최신 콜백을 참조만 해서, 콜백이 바뀌어도 폴링이 다시 시작되지 않게 합니다.
  const settledRef = useRef(onSettled);
  settledRef.current = onSettled;

  // 완료 통지를 작업당 한 번만 보냅니다.
  const notified = useRef(new Set<string>());

  // 배열 identity가 매 렌더 바뀌므로 내용으로 비교합니다.
  const key = jobIds.join(",");

  useEffect(() => {
    const ids = key ? key.split(",") : [];
    if (ids.length === 0) return;

    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let pending = new Set(ids);

    const tick = async () => {
      const results = await Promise.allSettled(
        [...pending].map((id) => api.getJob(id, controller.signal)),
      );
      if (controller.signal.aborted) return;

      const updates: Record<string, ProcessingJob> = {};
      for (const result of results) {
        if (result.status !== "fulfilled") continue;

        const job = result.value;
        updates[job.id] = job;

        if (isTerminal(job)) {
          pending.delete(job.id);
          if (!notified.current.has(job.id)) {
            notified.current.add(job.id);
            settledRef.current?.(job);
          }
        }
      }

      setJobs((current) => ({ ...current, ...updates }));
      if (pending.size > 0) timer = setTimeout(tick, POLL_INTERVAL_MS);
    };

    void tick();

    return () => {
      controller.abort();
      clearTimeout(timer);
      pending = new Set();
    };
  }, [key, api]);

  return jobs;
}
