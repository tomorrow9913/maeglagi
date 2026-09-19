"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useApi, useDemoMode } from "@/lib/api/context";
import type { ProcessingJob, Source } from "@/lib/api";
import { useWorkspaceSourceEvents } from "./use-workspace-source-events";

const isPending = (status: Source["status"]) => status === "queued" || status === "enqueue_pending" || status === "processing";

export function useLiveSources(workspaceId: string, watchReviewStates = false) {
  const api = useApi();
  const isDemo = useDemoMode();
  const [snapshot, setSnapshot] = useState<{ workspaceId: string; sources: Source[] }>();
  const [progressState, setProgress] = useState<{ workspaceId: string; values: Record<string, number> }>();
  const [errorState, setError] = useState<{ workspaceId: string; error: Error }>();
  const [nonce, setNonce] = useState(0);
  const settled = useRef<{ workspaceId: string; statuses: Map<string, Source["status"]> }>({ workspaceId, statuses: new Map() });
  const invalidated = useRef<{ workspaceId: string; ids: Set<string> }>({ workspaceId, ids: new Set() });
  if (settled.current.workspaceId !== workspaceId) settled.current = { workspaceId, statuses: new Map() };
  if (invalidated.current.workspaceId !== workspaceId) invalidated.current = { workspaceId, ids: new Set() };
  const sources = snapshot?.workspaceId === workspaceId ? snapshot.sources : undefined;
  const progress = progressState?.workspaceId === workspaceId ? progressState.values : {};
  const error = errorState?.workspaceId === workspaceId ? errorState.error : undefined;
  const reload = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    api.listSources(workspaceId, controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      setSnapshot({ workspaceId, sources: data });
      if (settled.current.workspaceId === workspaceId) {
        for (const source of data) {
          if (isPending(source.status)) settled.current.statuses.delete(source.id);
          else settled.current.statuses.set(source.id, source.status);
        }
      }
      if (invalidated.current.workspaceId === workspaceId) for (const id of invalidated.current.ids) if (!data.some((source) => source.id === id)) invalidated.current.ids.delete(id);
      setError(undefined);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError({ workspaceId, error: cause instanceof Error ? cause : new Error(String(cause)) });
    });
    return () => controller.abort();
  }, [api, workspaceId, nonce]);

  const onJob = useCallback((job: ProcessingJob) => {
    setSnapshot((current) => {
      if (!current || current.workspaceId !== workspaceId) return current;
      const index = current.sources.findIndex((source) => source.id === job.sourceId);
      if (index < 0 || current.sources[index].status === job.status) return current;
      const updated = [...current.sources];
      updated[index] = { ...updated[index], status: job.status };
      return { workspaceId, sources: updated };
    });
    setProgress((current) => {
      const values = current?.workspaceId === workspaceId ? current.values : {};
      return values[job.sourceId] === job.progress ? current : { workspaceId, values: { ...values, [job.sourceId]: job.progress } };
    });
    if (!isPending(job.status) && settled.current.workspaceId === workspaceId && settled.current.statuses.get(job.sourceId) !== job.status) {
      settled.current.statuses.set(job.sourceId, job.status);
      reload();
    }
  }, [reload, workspaceId]);

  useWorkspaceSourceEvents(workspaceId, sources?.filter((source) => isPending(source.status) || (watchReviewStates && (source.status === "awaiting_review" || source.status === "awaiting_agent"))).map((source) => source.id) ?? [], onJob, !isDemo, (sourceId) => {
    if (invalidated.current.workspaceId !== workspaceId || invalidated.current.ids.has(sourceId)) return;
    invalidated.current.ids.add(sourceId);
    reload();
  });

  useEffect(() => {
    window.addEventListener("maeglagi:sources-changed", reload);
    return () => window.removeEventListener("maeglagi:sources-changed", reload);
  }, [reload]);

  return { sources, progress, error, isLoading: !sources && !error, reload };
}
