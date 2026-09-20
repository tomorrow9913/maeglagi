"use client";

import { useEffect, useRef, useState } from "react";
import type { ProcessingJob } from "@/lib/api";
import { useWorkspaceSourceEvents } from "./use-workspace-source-events";

const isTerminal = (job: ProcessingJob) => job.status === "succeeded" || job.status === "failed" || job.status === "awaiting_review" || job.status === "awaiting_agent";
export type LiveJob = ProcessingJob & { eventError?: string };

/** Tracks uploaded jobs through the shared source stream and keeps their last state across reconnects. Also reports the stream connection state. */
export function useJobEvents(workspaceId: string, initialJobs: ProcessingJob[], onSettled?: (job: ProcessingJob) => void, restartKey = 0) {
  const [state, setState] = useState<{ workspaceId: string; restartKey: number; jobs: Record<string, LiveJob> }>({ workspaceId, restartKey, jobs: {} });
  const [invalidState, setInvalid] = useState<{ workspaceId: string; ids: Set<string> }>({ workspaceId, ids: new Set() });
  const jobs = state.workspaceId === workspaceId && state.restartKey === restartKey ? state.jobs : {};
  const invalidIds = invalidState.workspaceId === workspaceId ? invalidState.ids : new Set<string>();
  const callback = useRef(onSettled);
  callback.current = onSettled;
  const notified = useRef(new Map<string, ProcessingJob["status"]>());
  const previousContext = useRef({ workspaceId, restartKey });
  if (previousContext.current.workspaceId !== workspaceId || previousContext.current.restartKey !== restartKey) {
    previousContext.current = { workspaceId, restartKey };
    notified.current.clear();
  }
  useEffect(() => { if (state.workspaceId !== workspaceId || state.restartKey !== restartKey) setState({ workspaceId, restartKey, jobs: {} }); }, [workspaceId, restartKey, state.workspaceId, state.restartKey]);

  const notify = (job: ProcessingJob) => {
    if (!isTerminal(job) || notified.current.get(job.id) === job.status) return;
    notified.current.set(job.id, job.status);
    callback.current?.(job);
  };
  const initialKey = initialJobs.map((job) => `${job.id}:${job.status}`).join(",");
  useEffect(() => { for (const job of initialJobs) notify(job); }, [initialKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const sourceIds = initialJobs.filter((job) => !invalidIds.has(job.sourceId) && (restartKey > 0 && !jobs[job.id] || !isTerminal(jobs[job.id] ?? job))).map((job) => job.sourceId);
  const connection = useWorkspaceSourceEvents(workspaceId, sourceIds, (job) => {
    setState((current) => {
      const previous = current.workspaceId === workspaceId && current.restartKey === restartKey ? current.jobs[job.id] : undefined;
      if (previous && JSON.stringify(previous) === JSON.stringify(job)) return current;
      return { workspaceId, restartKey, jobs: { ...(current.workspaceId === workspaceId && current.restartKey === restartKey ? current.jobs : {}), [job.id]: job } };
    });
    notify(job);
  }, true, (sourceId) => {
    setInvalid((current) => {
      const ids = new Set(current.workspaceId === workspaceId ? current.ids : []);
      ids.add(sourceId);
      return { workspaceId, ids };
    });
    setState((current) => {
      const jobs = current.workspaceId === workspaceId && current.restartKey === restartKey ? { ...current.jobs } : {};
      for (const initial of initialJobs) if (initial.sourceId === sourceId) jobs[initial.id] = {
        ...(jobs[initial.id] ?? initial),
        eventError: "처리 상태를 확인하지 못했습니다. 소스 목록에서 확인해 주세요.",
      };
      return { workspaceId, restartKey, jobs };
    });
  });

  return { jobs, connection };
}
